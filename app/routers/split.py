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

    # 3. Parse assignment_date from string to date object
    try:
        assignment_date = datetime.strptime(request.assignment_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid assignment_date format. Expected YYYY-MM-DD")

    # 4. Validate ZIP filename date matches assignment date
    if request.zip_filename:
        # Extract date from filename (e.g., "2026 06 05 DBS.zip" -> "2026-06-05")
        try:
            parts = request.zip_filename.replace('.zip', '').replace('.rar', '').split()
            # Expected parts: ['2026', '06', '05', 'DBS']
            if len(parts) >= 3:
                year, month, day = parts[0], parts[1], parts[2]
                file_date = date(int(year), int(month), int(day))
                if file_date != assignment_date:
                    raise HTTPException(400, f"ZIP file date ({file_date}) does not match assignment date ({assignment_date})")
            else:
                raise HTTPException(400, "ZIP filename does not match expected format 'YYYY MM DD ...'")
        except ValueError as e:
            raise HTTPException(400, f"Could not parse date from ZIP filename: {str(e)}")    # 5. Get assignments for this agent on this date
    assignments = db.query(Assignment).filter(
        Assignment.assignment_date == assignment_date,
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
        existing_split = db.query(AgentSplit).filter(
            AgentSplit.session_id == request.session_id,
            AgentSplit.agent_id == agent.id,
            AgentSplit.lottery_code == assignment.lottery_code,
            AgentSplit.draw_number == order.draw_number
            ).first()
        if existing_split:
            raise HTTPException(409, f"Already split {assignment.lottery_code} draw {order.draw_number} for {agent.name}")
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
@router.get("/validate-upload")
def validate_upload(
    date: str = Query(...),
    db: Session = Depends(get_db)
):
    """Compare uploaded DBF record counts against ordered quantities for a date."""
    try:
        selected_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD)")

    # Get the session for this date
    session = db.query(Session).filter(
        Session.session_date == selected_date
    ).order_by(Session.uploaded_at.desc()).first()

    if not session:
        return {
            "upload_exists": False,
            "message": "No archive uploaded for this date.",
            "mismatches": [],
            "missing_lotteries": [],
            "extra_lotteries": [],
            "is_valid": False
        }

    # Get uploaded files
    uploaded_files = db.query(LotteryFile).filter(
        LotteryFile.session_id == session.id
    ).all()

    # Get orders for this date
    orders = db.query(Order).filter(
        Order.order_date == selected_date
    ).all()

    # Build lookup dictionaries
    uploaded_dict = {}
    for uf in uploaded_files:
        lt = db.query(LotteryType).filter_by(code=uf.lottery_name).first()
        uploaded_dict[uf.lottery_name] = {
            "lottery_code": uf.lottery_name,
            "lottery_name": lt.name if lt else uf.lottery_name,
            "draw_number": uf.draw_number,
            "record_count": uf.record_count,
            "start_serial": uf.start_serial,
            "end_serial": uf.end_serial
        }

    order_dict = {}
    for o in orders:
        lt = db.query(LotteryType).filter_by(code=o.lottery_code).first()
        order_dict[o.lottery_code] = {
            "lottery_code": o.lottery_code,
            "lottery_name": lt.name if lt else o.lottery_code,
            "draw_number": o.draw_number,
            "quantity": o.quantity
        }

    mismatches = []
    missing_lotteries = []
    extra_lotteries = []

    # Check each uploaded file against orders
    for code, upload in uploaded_dict.items():
        if code in order_dict:
            order = order_dict[code]
            draw_mismatch = upload["draw_number"] != order["draw_number"]
            count_mismatch = upload["record_count"] != order["quantity"]
            
            if draw_mismatch or count_mismatch:
                mismatches.append({
                    "lottery_code": code,
                    "lottery_name": upload["lottery_name"],
                    "ordered_draw": order["draw_number"],
                    "uploaded_draw": upload["draw_number"],
                    "draw_match": not draw_mismatch,
                    "ordered_quantity": order["quantity"],
                    "uploaded_records": upload["record_count"],
                    "count_match": not count_mismatch,
                    "difference": upload["record_count"] - order["quantity"]
                })
        else:
            extra_lotteries.append({
                "lottery_code": code,
                "lottery_name": upload["lottery_name"],
                "record_count": upload["record_count"]
            })

    # Check for orders without uploaded files
    for code, order in order_dict.items():
        if code not in uploaded_dict:
            missing_lotteries.append({
                "lottery_code": code,
                "lottery_name": order["lottery_name"],
                "quantity": order["quantity"]
            })

    is_valid = len(mismatches) == 0 and len(missing_lotteries) == 0 and len(extra_lotteries) == 0

    return {
        "upload_exists": True,
        "session_id": session.id,
        "is_valid": is_valid,
        "mismatches": mismatches,
        "missing_lotteries": missing_lotteries,
        "extra_lotteries": extra_lotteries,
        "summary": {
            "total_uploaded": len(uploaded_files),
            "total_ordered": len(orders),
            "total_mismatches": len(mismatches),
            "total_missing": len(missing_lotteries),
            "total_extra": len(extra_lotteries)
        }
    }
@router.get("/splits-by-date")
def list_splits_by_date(
    agent_name: str = Query(...),
    date: str = Query(...),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    try:
        qdate = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD)")

    splits = (
        db.query(AgentSplit)
        .join(Session, AgentSplit.session_id == Session.id)
        .filter(
            AgentSplit.agent_id == agent.id,
            Session.session_date == qdate
        )
        .all()
    )

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
            "filename": os.path.basename(s.saved_file_path),   # <-- add this
            "download_url": f"/api/v1/download-file/{os.path.basename(s.saved_file_path)}?session={s.session_id}",
            "session_id": s.session_id,
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


@router.get("/split-dates/{agent_name}")
def get_split_dates(agent_name: str, db: Session = Depends(get_db)):
    """Get all dates that have splits for a specific agent"""
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    # Get all unique session_dates that have splits for this agent
    splits = db.query(AgentSplit, Session.session_date).join(
        Session, AgentSplit.session_id == Session.id
    ).filter(
        AgentSplit.agent_id == agent.id,
        Session.session_date.isnot(None)
    ).distinct().all()
    
    dates = [str(s[1]) for s in splits]  # Convert dates to strings
    return {"dates": sorted(list(set(dates)))}  # Remove duplicates and sort