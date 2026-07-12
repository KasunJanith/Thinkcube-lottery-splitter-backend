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
from app.utils.dbf_splitter import split_single_lottery_for_agent, _get_serial_field
from app.config import STORAGE_BASE
from app.models import SpecialSplit

router = APIRouter()

class SplitRequest(BaseModel):
    session_id: str
    agent_name: str
    assignment_date: str
    zip_filename: Optional[str] = None

class SpecialSplitRequest(BaseModel):
    session_id: str
    agent_name: str
    assignment_date: str
    counts: List[dict]   # [{"lottery_code": "ada", "count": 20}, ...]
    label: Optional[str] = None   # optional, otherwise auto‑generated

@router.post("/special-split")
def create_special_split(request: SpecialSplitRequest, db: Session = Depends(get_db)):
    # Validate agent and date
    agent = db.query(Agent).filter(Agent.name == request.agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    try:
        assignment_date = datetime.strptime(request.assignment_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid date format")

    # Find the daytime session
    session = db.query(Session).filter(Session.id == request.session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    # Get the original agent splits for this agent/date
    agent_splits = db.query(AgentSplit).filter(
        AgentSplit.session_id == request.session_id,
        AgentSplit.agent_id == agent.id
    ).all()
    if not agent_splits:
        raise HTTPException(400, "No daytime splits found for this agent/date")

    split_map = {sp.lottery_code: sp for sp in agent_splits}
    results = []

    for item in request.counts:
        lottery_code = item["lottery_code"]
        count = item["count"]
        if count <= 0:
            continue

        original_split = split_map.get(lottery_code)
        if not original_split:
            raise HTTPException(400, f"No split found for lottery {lottery_code}")

        # Calculate how many records are already used by existing special splits
        existing_specials = db.query(SpecialSplit).filter(
            SpecialSplit.agent_split_id == original_split.id
        ).all()

        # Determine the last serial used in any special split (assuming sequential allocation)
        max_end_serial = None
        for sp in existing_specials:
            if max_end_serial is None or sp.end_serial > max_end_serial:
                max_end_serial = sp.end_serial

        # Read original split file, sorted by serial
        from dbfread import DBF
        dbf_obj = DBF(original_split.saved_file_path, encoding='utf-8')
        serial_field = _get_serial_field(dbf_obj)
        records = []
        for rec in dbf_obj:
            serial = rec[serial_field].strip()
            records.append((serial, rec))
        records.sort(key=lambda x: x[0])

        # Filter out records already used (serial <= max_end_serial)
        if max_end_serial:
            available = [(s, r) for s, r in records if s > max_end_serial]
        else:
            available = records[:]  # all are available

        if len(available) < count:
            raise HTTPException(
                400,
                f"Not enough remaining records in {lottery_code} for special split. "
                f"Requested {count}, available {len(available)}."
            )

        # Take the next `count` records
        chunk = available[:count]
        start_serial = chunk[0][0]
        end_serial = chunk[-1][0]

        # Generate label
        if request.label:
            label = request.label
        else:
            # Auto label: "Special Split 1", "Special Split 2" ... per original split
            num_existing = len(existing_specials)
            label = f"Special Split {num_existing + 1}"

        # Write new DBF
        output_dir = os.path.join(STORAGE_BASE, request.session_id, "special_splits")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{lottery_code}_{original_split.draw_number}_{agent.name}_{label.replace(' ', '_')}.dbf"
        output_path = os.path.join(output_dir, output_filename)

        # Clone structure
        source = dbf.Table(original_split.saved_file_path)
        source.open(dbf.READ_ONLY)
        new = source.new(output_path)
        new.open(dbf.READ_WRITE)
        for _, rec in chunk:
            row = {name: rec.get(name) for name in dbf_obj.field_names}
            new.append(row)
        new.close()
        source.close()

        special = SpecialSplit(
            agent_split_id=original_split.id,
            label=label,
            lottery_code=lottery_code,
            draw_number=original_split.draw_number,
            start_serial=start_serial,
            end_serial=end_serial,
            record_count=len(chunk),
            saved_file_path=output_path
        )
        db.add(special)
        results.append({
            "lottery_code": lottery_code,
            "label": label,
            "record_count": len(chunk),
            "start_serial": start_serial,
            "end_serial": end_serial
        })

    db.commit()
    return {"status": "completed", "specials": results}

@router.get("/special-splits")
def get_special_splits(
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
        raise HTTPException(400, "Invalid date format")

    # Find all special splits for this agent/date via AgentSplit
    specials = db.query(SpecialSplit).join(AgentSplit).join(Session).filter(
        AgentSplit.agent_id == agent.id,
        Session.session_date == qdate
    ).order_by(SpecialSplit.created_at).all()

    result = []
    for sp in specials:
        lt = db.query(LotteryType).filter_by(code=sp.lottery_code).first()
        result.append({
            "id": sp.id,
            "label": sp.label,
            "lottery_code": sp.lottery_code,
            "lottery_name": lt.name if lt else sp.lottery_code,
            "draw_number": sp.draw_number,
            "start_serial": sp.start_serial,
            "end_serial": sp.end_serial,
            "record_count": sp.record_count,
            "filename": os.path.basename(sp.saved_file_path),
            "session_id": sp.agent_split.session_id   # need agent_split relationship loaded
        })
    return result
@router.get("/download-special-file/{filename}")
def download_special_file(filename: str, session: str):
    file_path = os.path.join(STORAGE_BASE, session, "special_splits", filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")
    return FileResponse(file_path, media_type="application/octet-stream", filename=filename)

@router.post("/split-for-agent")
def split_for_agent(request: SplitRequest, db: Session = Depends(get_db)):
    # --- Validate session, agent, date (same as before) ---
    session = db.query(Session).filter(Session.id == request.session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")

    agent = db.query(Agent).filter(Agent.name == request.agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    try:
        assignment_date = datetime.strptime(request.assignment_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid assignment_date format. Expected YYYY-MM-DD")

    if request.zip_filename:
        try:
            parts = request.zip_filename.replace('.zip', '').replace('.rar', '').split()
            if len(parts) >= 3:
                file_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                if file_date != assignment_date:
                    raise HTTPException(400, f"ZIP file date ({file_date}) does not match assignment date ({assignment_date})")
        except ValueError as e:
            raise HTTPException(400, f"Could not parse date from ZIP filename: {str(e)}")

    # --- Get ALL assignments for this date (both agents) ---
    all_assignments = db.query(Assignment).filter(
        Assignment.assignment_date == assignment_date
    ).all()
    if not all_assignments:
        raise HTTPException(400, "No assignments found for this date")

    # Get agents and sort them to define the order (alphabetical: JAYAWAY, WINWAY)
    agent_ids = {a.agent_id for a in all_assignments}
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).order_by(Agent.name).all()
    agent_order = [ag.id for ag in agents]  # e.g., [JAYAWAY.id, WINWAY.id]

    # Get orders (draw numbers)
    orders = db.query(Order).filter(Order.order_date == request.assignment_date).all()
    if not orders:
        raise HTTPException(400, "No orders found for this date")

    # Group orders by lottery_code
    order_map = {o.lottery_code: o for o in orders}

    results = []

    # Process each lottery
    lottery_codes = set(a.lottery_code for a in all_assignments)
    for lcode in lottery_codes:
        order = order_map.get(lcode)
        if not order:
            raise HTTPException(400, f"Order not found for lottery {lcode}")

        # Find the DBF file
        dbf_file = db.query(LotteryFile).filter(
            LotteryFile.session_id == request.session_id,
            LotteryFile.lottery_name == lcode,
            LotteryFile.draw_number == order.draw_number
        ).first()
        if not dbf_file:
            raise HTTPException(400, f"DBF file not found for {lcode} draw {order.draw_number}")

        # Check if this specific agent already has a split for this lottery
        existing = db.query(AgentSplit).filter(
            AgentSplit.session_id == request.session_id,
            AgentSplit.agent_id == agent.id,
            AgentSplit.lottery_code == lcode,
            AgentSplit.draw_number == order.draw_number
        ).first()
        if existing:
            raise HTTPException(409, f"Already split {lcode} for {agent.name}")

        # --- Calculate the starting index for this agent ---
        # Sum the assigned counts of all agents that come BEFORE this agent in sorted order
        target_agent_index = agent_order.index(agent.id)
        start_index = 0
        for idx in range(target_agent_index):
            earlier_agent_id = agent_order[idx]
            earlier_assignment = next(
                (a for a in all_assignments if a.lottery_code == lcode and a.agent_id == earlier_agent_id),
                None
            )
            if earlier_assignment:
                start_index += earlier_assignment.assigned_count

        # This agent's own count
        this_assignment = next(
            (a for a in all_assignments if a.lottery_code == lcode and a.agent_id == agent.id),
            None
        )
        if not this_assignment or this_assignment.assigned_count <= 0:
            continue

        count_to_split = this_assignment.assigned_count

        # Safety: ensure we don't exceed file length
        if start_index + count_to_split > dbf_file.record_count:
            raise HTTPException(400, f"Not enough records for {agent.name} in {lcode}. "
                                      f"Start {start_index} + count {count_to_split} exceeds total {dbf_file.record_count}")

        # Now split using a helper that can start from an offset, not just the beginning
        part_info = split_with_offset(
            dbf_file.stored_path,
            start_index,
            count_to_split,
            dbf_file.serial_field
        )

        # Save the new AgentSplit
        output_dir = os.path.join(STORAGE_BASE, request.session_id, "splits")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{lcode}_{order.draw_number}_{agent.name}.dbf"
        output_path = os.path.join(output_dir, output_filename)

        # Write the chunk to DBF
        _write_chunk_to_dbf(dbf_file.stored_path, output_path, part_info["records"])

        new_split = AgentSplit(
            session_id=request.session_id,
            agent_id=agent.id,
            lottery_code=lcode,
            draw_number=order.draw_number,
            start_serial=part_info["start_serial"],
            end_serial=part_info["end_serial"],
            record_count=part_info["record_count"],
            saved_file_path=output_path
        )
        db.add(new_split)
        results.append({
            "lottery_code": lcode,
            "start_serial": part_info["start_serial"],
            "end_serial": part_info["end_serial"],
            "record_count": part_info["record_count"]
        })

    db.commit()
    return {"status": "split completed", "files": results}


def split_with_offset(file_path: str, offset: int, count: int, serial_field: str) -> dict:
    """Extract a slice of records from a DBF file, starting at `offset` (0-indexed)."""
    from dbfread import DBF
    dbf_obj = DBF(file_path, encoding='utf-8')
    records = []
    for rec in dbf_obj:
        serial = rec.get(serial_field, '').strip()
        records.append((serial, rec))
    records.sort(key=lambda x: x[0])
    if offset + count > len(records):
        raise ValueError("Not enough records")
    chunk = records[offset:offset + count]
    return {
        "start_serial": chunk[0][0],
        "end_serial": chunk[-1][0],
        "record_count": len(chunk),
        "records": [r for _, r in chunk]   # actual record dicts
    }


def _write_chunk_to_dbf(source_path: str, output_path: str, records: list):
    """Write a list of record dicts to a new DBF with the same structure as source."""
    import dbf
    source = dbf.Table(source_path)
    source.open(dbf.READ_ONLY)
    new = source.new(output_path)
    new.open(dbf.READ_WRITE)
    for rec in records:
        new.append(rec)
    new.close()
    source.close()


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
        # Try to find the original DBF filename from LotteryFile
        original_filename = s.lottery_code + "_" + s.draw_number + ".dbf"   # fallback
        lf = db.query(LotteryFile).filter(
            LotteryFile.session_id == session_id,
            LotteryFile.lottery_name == s.lottery_code,
            LotteryFile.draw_number == s.draw_number
        ).first()
        if lf:
            original_filename = os.path.basename(lf.stored_path)   # the original filename from upload
        lt = db.query(LotteryType).filter_by(code=s.lottery_code).first()
        result.append({
            "lottery_code": s.lottery_code,
            "lottery_name": lt.name if lt else s.lottery_code,
            "draw_number": s.draw_number,
            "start_serial": s.start_serial,
            "end_serial": s.end_serial,
            "record_count": s.record_count,
            "filename": os.path.basename(s.saved_file_path),           # stored filename
            "original_filename": original_filename,                    # original from upload
            "download_url": f"/api/v1/download-file/{os.path.basename(s.saved_file_path)}?session={session_id}&original_name={original_filename}",
            "session_id": s.session_id,
        })
    return result

@router.get("/download-file/{filename}")
def download_file(
    filename: str,
    session: str,
    original_name: Optional[str] = Query(None)   # optional original filename for Content-Disposition
):
    file_path = os.path.join(STORAGE_BASE, session, "splits", filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")
    download_name = original_name if original_name else filename
    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=download_name
    )

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
                # Determine the original filename to use inside ZIP
                original_name = None
                lf = db.query(LotteryFile).filter(
                    LotteryFile.session_id == session_id,
                    LotteryFile.lottery_name == s.lottery_code,
                    LotteryFile.draw_number == s.draw_number
                ).first()
                if lf:
                    original_name = os.path.basename(lf.stored_path)
                if not original_name:
                    original_name = f"{s.lottery_code}_{s.draw_number}.dbf"
                zf.write(s.saved_file_path, original_name)
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