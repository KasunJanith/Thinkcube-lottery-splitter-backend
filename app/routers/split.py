import os
import io
import zipfile
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import Session, LotteryFile, AgentSplit, Agent, Assignment, Order, LotteryType
from app.utils.dbf_splitter import split_single_lottery_for_agent
from app.config import STORAGE_BASE

router = APIRouter()

class SplitRequest(BaseModel):
    session_id: str
    agent_name: str
    assignment_date: str       # "YYYY-MM-DD"
    zip_filename: Optional[str] = None   # original zip filename, e.g., "2026 05 21 DBS.zip"

@router.post("/split-for-agent")
def split_for_agent(request: SplitRequest, db: Session = Depends(get_db)):
    # 1. Validate session
    session = db.query(Session).filter(Session.id == request.session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    # 2. Verify agent exists
    agent = db.query(Agent).filter(Agent.name == request.agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # 3. Validate ZIP filename date matches assignment date
    if request.zip_filename:
        # Extract date from filename (e.g., "2026 05 21 DBS.zip" -> "2026-05-21")
        try:
            parts = request.zip_filename.replace('.zip', '').split()
            # Expected parts: ['2026', '05', '21', 'DBS']
            if len(parts) >= 3:
                year, month, day = parts[0], parts[1], parts[2]
                file_date = date(int(year), int(month), int(day))
                assignment_date = datetime.strptime(request.assignment_date, "%Y-%m-%d").date()
                if file_date != assignment_date:
                    raise HTTPException(400, f"ZIP file date ({file_date}) does not match assignment date ({assignment_date})")
            else:
                raise HTTPException(400, "ZIP filename does not match expected format 'YYYY MM DD ...'")
        except ValueError:
            raise HTTPException(400, "Could not parse date from ZIP filename")

    # 4. Get assignments for this agent on this date
    assignments = db.query(Assignment).filter(
        Assignment.assignment_date == request.assignment_date,
        Assignment.agent_id == agent.id
    ).all()
    if not assignments:
        raise HTTPException(400, "No assignments found for this agent/date")

    # 5. Get orders (draw numbers)
    orders = db.query(Order).filter(Order.order_date == request.assignment_date).all()
    if not orders:
        raise HTTPException(400, "No orders found for this date")

    # 6. Process each lottery
    results = []
    for assignment in assignments:
        if assignment.assigned_count <= 0:
            continue
        order = next((o for o in orders if o.lottery_code == assignment.lottery_code), None)
        if not order:
            raise HTTPException(400, f"Draw number not found for lottery {assignment.lottery_code}")

        # Find the corresponding DBF file in the session
        dbf_file = db.query(LotteryFile).filter(
            LotteryFile.session_id == request.session_id,
            LotteryFile.lottery_name == assignment.lottery_code,
            LotteryFile.draw_number == order.draw_number
        ).first()
        if not dbf_file:
            raise HTTPException(400, f"DBF file not found for {assignment.lottery_code} draw {order.draw_number}")

        # Split: take first assigned_count records
        input_path = dbf_file.stored_path
        output_filename = f"{assignment.lottery_code}_{order.draw_number}_{agent.name}.dbf"
        output_dir = os.path.join(STORAGE_BASE, request.session_id, "splits")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        part_info = split_single_lottery_for_agent(
            input_path, output_path, assignment.assigned_count,
            dbf_file.serial_field
        )

        # Save record in AgentSplit
        new_split = AgentSplit(
            session_id=request.session_id,
            agent_id=agent.id,
            lottery_code=assignment.lottery_code,
            draw_number=order.draw_number,
            start_serial=part_info["start_serial"],
            end_serial=part_info["end_serial"],
            record_count=part_info["record_count"],
            saved_file_path=output_path
        )
        db.add(new_split)
        results.append({
            "lottery_code": assignment.lottery_code,
            "start_serial": part_info["start_serial"],
            "end_serial": part_info["end_serial"],
            "record_count": part_info["record_count"]
        })

    db.commit()
    return {"status": "split completed", "files": results}


# --- Preview assigned counts for an agent (used by frontend) ---
@router.get("/assigned-counts")
def get_assigned_counts(
    agent_name: str = Query(...),
    assignment_date: str = Query(...),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    assignments = db.query(Assignment).filter(
        Assignment.assignment_date == assignment_date,
        Assignment.agent_id == agent.id
    ).all()

    orders = db.query(Order).filter(Order.order_date == assignment_date).all()
    lottery_types = db.query(LotteryType).all()

    result = []
    for lt in lottery_types:
        order = next((o for o in orders if o.lottery_code == lt.code), None)
        assign = next((a for a in assignments if a.lottery_code == lt.code), None)
        result.append({
            "lottery_code": lt.code,
            "lottery_name": lt.name,
            "draw_number": order.draw_number if order else "",
            "assigned_count": assign.assigned_count if assign else 0,
            "available_quantity": order.quantity if order else 0,
        })
    return result


# --- Download endpoints (unchanged) ---
@router.get("/agent-splits/{session_id}/{agent_name}")
def list_agent_splits(session_id: str, agent_name: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    splits = db.query(AgentSplit).filter(
        AgentSplit.session_id == session_id,
        AgentSplit.agent_id == agent.id
    ).all()
    result = []
    for s in splits:
        lt = db.query(LotteryType).filter_by(code=s.lottery_code).first()
        result.append({
            "lottery_code": s.lottery_code,
            "lottery_name": lt.name if lt else s.lottery_code,
            "draw_number": s.draw_number,
            "start_serial": s.start_serial,
            "end_serial": s.end_serial,
            "record_count": s.record_count,
            "saved_file_path": s.saved_file_path,
            "download_url": f"/api/v1/download-file/{os.path.basename(s.saved_file_path)}?session={session_id}"
        })
    return result

@router.get("/download-file/{filename}")
def download_file(filename: str, session: str):
    file_path = os.path.join(STORAGE_BASE, session, "splits", filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)

@router.get("/download-agent-zip/{session_id}/{agent_name}")
def download_agent_zip(session_id: str, agent_name: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    splits = db.query(AgentSplit).filter(
        AgentSplit.session_id == session_id,
        AgentSplit.agent_id == agent.id
    ).all()
    if not splits:
        raise HTTPException(404, "No splits found")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in splits:
            if os.path.exists(s.saved_file_path):
                zf.write(s.saved_file_path, os.path.basename(s.saved_file_path))
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={agent_name}_splits.zip"}
    )