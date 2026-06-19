import os
import io
import zipfile
import tempfile
import shutil
import uuid
import re
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Query, Form
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import dbf
from dbfread import DBF
from collections import defaultdict

from app.database import get_db
from app.config import STORAGE_BASE, EXPECTED_DBF_COUNT, ALLOWED_EXTENSIONS
from app.models import (
    Session, LotteryFile, AgentSplit, Agent, Assignment, Order, LotteryType,
    WinningSession, WinningFile, AgentWinningSplit
)
from app.utils.archive_handler import is_valid_archive, extract_archive
from app.utils.dbf_splitter import _get_serial_field

router = APIRouter()

# ----------------------------------------------------------------------
# Helper: map winning file code (e.g., ADE) to our lottery_code (e.g., ada)
# ----------------------------------------------------------------------
def map_winning_code_to_lottery(code: str) -> Optional[str]:
    mapping = {
        'ADE': 'ada',
        'DNE': 'dana',
        'GSE': 'GOVI',
        'HAE': 'HADA',
        'MPE': 'mgap',
        'MSE': 'Maha',
        'NJE': 'Jaya',
        'SDE': 'SUBA'
    }
    return mapping.get(code.upper())

# ----------------------------------------------------------------------
# Helper: extract date from zip filename
# ----------------------------------------------------------------------
def extract_date_from_zip(filename: str):
    parts = filename.replace('.zip', '').replace('.ZIP', '').split()
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    return None

# ----------------------------------------------------------------------
# 1. Upload Winning Archive
# ----------------------------------------------------------------------
@router.post("/upload-winning-archive")
async def upload_winning_archive(
    file: UploadFile = File(...),
    date: Optional[str] = Form(None),       # <-- NEW: date from frontend
    db: Session = Depends(get_db)
):
    if not file:
        raise HTTPException(400, "No file uploaded.")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Invalid file type '{ext}'.")

    # Save temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    tmp_dir = tempfile.mkdtemp()
    try:
        if not is_valid_archive(tmp_path):
            raise HTTPException(400, "Invalid archive.")
        extract_archive(tmp_path, tmp_dir)

        # Find all .dbf files
        dbf_files = []
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith('.dbf'):
                    dbf_files.append(os.path.join(root, f))
        if len(dbf_files) != EXPECTED_DBF_COUNT:
            raise HTTPException(400, f"Expected {EXPECTED_DBF_COUNT} DBF files, found {len(dbf_files)}.")

        # Parse filenames: e.g., ADE0780.DBF, DNE2235.DBF
        pattern = re.compile(r'^([A-Za-z]{2,3})(\d{4})\.dbf$', re.IGNORECASE)
        winning_files = []
        for fpath in dbf_files:
            fname = os.path.basename(fpath)
            m = pattern.match(fname)
            if not m:
                raise HTTPException(400, f"Invalid winning filename: {fname}. Expected like ADE0780.DBF")
            code_raw = m.group(1).upper()
            draw = m.group(2)
            lottery_code = map_winning_code_to_lottery(code_raw)
            if not lottery_code:
                raise HTTPException(400, f"Unknown winning code: {code_raw}")
            winning_files.append((fpath, fname, lottery_code, draw))

        # --- Determine session_date ---
        session_date = None
        # 1) Try from the user‑provided date
        if date:
            try:
                session_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "Invalid date format (expected YYYY-MM-DD).")
        # 2) Fallback to filename
        if not session_date:
            zip_date_str = extract_date_from_zip(file.filename or "")
            if zip_date_str:
                try:
                    session_date = datetime.strptime(zip_date_str, "%Y-%m-%d").date()
                except:
                    pass
        # 3) Still no date → reject
        if not session_date:
            raise HTTPException(400, "Could not determine the draw date. Please provide a date or use a filename containing the date (e.g., '2026 06 17 winning.zip').")

        # Create WinningSession
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(STORAGE_BASE, "winning", session_id)
        os.makedirs(session_dir, exist_ok=True)

        # Process each winning file
        saved_files = []
        for fpath, fname, lottery_code, draw in winning_files:
            # Read DBF: count records & sum price
            dbf_obj = DBF(fpath, encoding='utf-8')
            serial_field = _get_serial_field(dbf_obj)  # CODE or PRN_CODE
            price_field = 'PRICE' if 'PRICE' in dbf_obj.field_names else 'AMOUNT'
            total_price = 0.0
            record_count = 0
            for rec in dbf_obj:
                record_count += 1
                total_price += float(rec.get(price_field, 0) or 0)

            # Copy to session dir
            dest = os.path.join(session_dir, fname)
            shutil.copy2(fpath, dest)

            wf = WinningFile(
                session_id=session_id,
                lottery_code=lottery_code,
                draw_number=draw,
                original_filename=fname,
                record_count=record_count,
                total_price=total_price,
                stored_path=dest
            )
            db.add(wf)
            saved_files.append({
                "lottery_code": lottery_code,
                "draw_number": draw,
                "record_count": record_count,
                "total_price": round(total_price, 2)
            })

        ws = WinningSession(
            id=session_id,
            original_filename=file.filename,
            session_date=session_date,
            status="extracted"
        )
        db.add(ws)
        db.commit()

        return {
            "success": True,
            "session_id": session_id,
            "files": saved_files,
            "session_date": str(session_date) if session_date else None
        }
    finally:
        os.unlink(tmp_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ----------------------------------------------------------------------
# 2. Get winning session by date
# ----------------------------------------------------------------------
@router.get("/winning-session-by-date")
def get_winning_session_by_date(date: str = Query(...), db: Session = Depends(get_db)):
    """Return the most recent winning session id for a given date."""
    try:
        qdate = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD).")
    
    session = (
        db.query(WinningSession)
        .filter(WinningSession.session_date == qdate)
        .order_by(WinningSession.uploaded_at.desc())
        .first()
    )
    if not session:
        return {"session_id": None, "message": "No winning session found for this date."}
    return {"session_id": session.id, "status": session.status}

# ----------------------------------------------------------------------
# 3. Validate winning files against daytime splits and orders
# ----------------------------------------------------------------------
@router.get("/validate-winning/{session_id}")
def validate_winning(session_id: str, db: Session = Depends(get_db)):
    ws = db.query(WinningSession).filter(WinningSession.id == session_id).first()
    if not ws:
        raise HTTPException(404, "Winning session not found")
    if not ws.session_date:
        raise HTTPException(400, "Winning session has no date; cannot validate.")

    # Daytime data session for the same date
    data_session = db.query(Session).filter(
        Session.session_date == ws.session_date
    ).order_by(Session.uploaded_at.desc()).first()
    if not data_session:
        raise HTTPException(400, "No daytime data upload found for this date.")

    # Orders (draw numbers)
    orders = db.query(Order).filter(Order.order_date == ws.session_date).all()
    order_draws = {o.lottery_code: o.draw_number for o in orders}

    # ALL daytime splits (both agents)
    agent_splits = db.query(AgentSplit).filter(
        AgentSplit.session_id == data_session.id
    ).all()

    # lottery_code -> list of (start, end) ranges from all agents
    ranges_by_lottery = defaultdict(list)
    for sp in agent_splits:
        ranges_by_lottery[sp.lottery_code].append((sp.start_serial, sp.end_serial))

    winning_files = db.query(WinningFile).filter(WinningFile.session_id == session_id).all()
    mismatches = []
    valid = True

    for wf in winning_files:
        # 1. Draw number check
        expected_draw = order_draws.get(wf.lottery_code)
        if not expected_draw or wf.draw_number != expected_draw:
            mismatches.append({
                "lottery": wf.lottery_code,
                "message": f"Draw mismatch: winning {wf.draw_number}, order {expected_draw}"
            })
            valid = False
            continue

        # 2. Get all ranges for this lottery
        lottery_ranges = ranges_by_lottery.get(wf.lottery_code, [])
        if not lottery_ranges:
            mismatches.append({
                "lottery": wf.lottery_code,
                "message": "No daytime split ranges found for this lottery"
            })
            valid = False
            continue

        # 3. Check every single record
        try:
            dbf_obj = DBF(wf.stored_path, encoding='utf-8')
            serial_field = _get_serial_field(dbf_obj)
            outside_serials = []
            total_records = 0
            for rec in dbf_obj:
                total_records += 1
                serial = rec[serial_field].strip()
                in_any_range = any(start <= serial <= end for (start, end) in lottery_ranges)
                if not in_any_range:
                    outside_serials.append(serial)

            if outside_serials:
                examples = outside_serials[:5]
                mismatches.append({
                    "lottery": wf.lottery_code,
                    "message": f"{len(outside_serials)} of {total_records} records are outside ALL agent ranges. Examples: {', '.join(examples)}{'...' if len(outside_serials) > 5 else ''}"
                })
                valid = False
        except Exception as e:
            mismatches.append({"lottery": wf.lottery_code, "message": f"Error reading file: {str(e)}"})
            valid = False

    # Update session status
    ws.status = "validated" if valid else "validation_failed"
    db.commit()

    return {
        "valid": valid,
        "mismatches": mismatches,
        "session_id": session_id,
        "date": str(ws.session_date)
    }

# ----------------------------------------------------------------------
# 4. Split winning files for a specific agent
# ----------------------------------------------------------------------
class SplitWinningRequest(BaseModel):
    session_id: str
    agent_name: str

@router.post("/split-winning")
def split_winning(request: SplitWinningRequest, db: Session = Depends(get_db)):
    ws = db.query(WinningSession).filter(WinningSession.id == request.session_id).first()
    if not ws:
        raise HTTPException(404, "Winning session not found")
    if ws.status != "validated":
        raise HTTPException(400, "Winning files must be validated first.")

    agent = db.query(Agent).filter(Agent.name == request.agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Daytime session
    data_session = db.query(Session).filter(Session.session_date == ws.session_date).first()
    if not data_session:
        raise HTTPException(400, "Daytime data session not found")

    # Daytime agent splits (ranges)
    agent_splits = db.query(AgentSplit).filter(
        AgentSplit.session_id == data_session.id,
        AgentSplit.agent_id == agent.id
    ).all()
    if not agent_splits:
        raise HTTPException(400, "No daytime splits for this agent.")
    range_map = {sp.lottery_code: (sp.start_serial, sp.end_serial) for sp in agent_splits}

    output_dir = os.path.join(STORAGE_BASE, "winning", request.session_id, "splits")
    os.makedirs(output_dir, exist_ok=True)

    results = []
    for wf in db.query(WinningFile).filter(WinningFile.session_id == request.session_id).all():
        if wf.lottery_code not in range_map:
            continue

        start_serial, end_serial = range_map[wf.lottery_code]

        # Read winning records
        dbf_obj = DBF(wf.stored_path, encoding='utf-8')
        serial_field = _get_serial_field(dbf_obj)
        price_field = 'PRICE' if 'PRICE' in dbf_obj.field_names else 'AMOUNT'

        filtered = []
        total_price = 0.0
        total_records_in_file = 0
        for rec in dbf_obj:
            total_records_in_file += 1
            serial = rec[serial_field].strip()
            if start_serial <= serial <= end_serial:
                filtered.append(rec)
                total_price += float(rec.get(price_field, 0) or 0)

        # SAFETY CHECK: if we filtered all records, it might mean the range covers the whole file
        if len(filtered) == total_records_in_file and total_records_in_file > 0:
            raise HTTPException(
                400,
                f"Agent {agent.name} appears to own ALL records of lottery {wf.lottery_code}. "
                f"Range {start_serial}-{end_serial} covers the entire winning file. "
                "Please verify the daytime split ranges."
            )

        if not filtered:
            continue

        output_filename = f"{wf.lottery_code}_{wf.draw_number}_{agent.name}.dbf"
        output_path = os.path.join(output_dir, output_filename)

        # Write DBF (clone structure)
        source = dbf.Table(wf.stored_path)
        source.open(dbf.READ_ONLY)
        new = source.new(output_path)
        new.open(dbf.READ_WRITE)
        for rec in filtered:
            row = {name: rec.get(name) for name in dbf_obj.field_names}
            new.append(row)
        new.close()
        source.close()

        split_entry = AgentWinningSplit(
            winning_session_id=request.session_id,
            agent_id=agent.id,
            lottery_code=wf.lottery_code,
            draw_number=wf.draw_number,
            record_count=len(filtered),
            total_price=total_price,
            saved_file_path=output_path
        )
        db.add(split_entry)
        results.append({
            "lottery_code": wf.lottery_code,
            "record_count": len(filtered),
            "total_price": round(total_price, 2),
            "file": output_filename,
            "range_used": f"{start_serial} – {end_serial}"
        })

    db.commit()
    return {"status": "completed", "files": results}

# ----------------------------------------------------------------------
# 5. List / Download endpoints
# ----------------------------------------------------------------------
@router.get("/agent-winning-splits/{session_id}/{agent_name}")
def list_agent_winning_splits(session_id: str, agent_name: str, db: Session = Depends(get_db)):
    # First find the agent
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    # Then get the splits
    splits = db.query(AgentWinningSplit).filter(
        AgentWinningSplit.winning_session_id == session_id,
        AgentWinningSplit.agent_id == agent.id
    ).all()
    
    result = []
    for s in splits:
        # Find the original winning filename from WinningFile
        original_filename = None
        wf = db.query(WinningFile).filter(
            WinningFile.session_id == session_id,
            WinningFile.lottery_code == s.lottery_code,
            WinningFile.draw_number == s.draw_number
        ).first()
        if wf:
            original_filename = os.path.basename(wf.stored_path)
        if not original_filename:
            original_filename = f"{s.lottery_code}_{s.draw_number}.dbf"
        
        lt = db.query(LotteryType).filter_by(code=s.lottery_code).first()
        result.append({
            "lottery_code": s.lottery_code,
            "lottery_name": lt.name if lt else s.lottery_code,
            "draw_number": s.draw_number,
            "record_count": s.record_count,
            "total_price": s.total_price,
            "filename": os.path.basename(s.saved_file_path),
            "original_filename": original_filename,
            "download_url": f"/api/v1/download-winning-file/{os.path.basename(s.saved_file_path)}?session={session_id}&original_name={original_filename}"
        })
    return result

@router.get("/download-winning-file/{filename}")
def download_winning_file(
    filename: str,
    session: str,
    original_name: Optional[str] = Query(None)
):
    file_path = os.path.join(STORAGE_BASE, "winning", session, "splits", filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found")
    download_name = original_name if original_name else filename
    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=download_name
    )
    
@router.get("/download-agent-winning-zip/{session_id}/{agent_name}")
def download_agent_winning_zip(session_id: str, agent_name: str, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.name == agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    splits = db.query(AgentWinningSplit).filter(
        AgentWinningSplit.winning_session_id == session_id,
        AgentWinningSplit.agent_id == agent.id
    ).all()
    if not splits:
        raise HTTPException(404, "No splits found")
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in splits:
            if os.path.exists(s.saved_file_path):
                original_name = None
                wf = db.query(WinningFile).filter(
                    WinningFile.session_id == session_id,
                    WinningFile.lottery_code == s.lottery_code,
                    WinningFile.draw_number == s.draw_number
                ).first()
                if wf:
                    original_name = os.path.basename(wf.stored_path)
                if not original_name:
                    original_name = f"{s.lottery_code}_{s.draw_number}.dbf"
                zf.write(s.saved_file_path, original_name)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={agent_name}_winning_splits.zip"}
    )
    
@router.get("/winning-files-by-date")
def get_winning_files_by_date(date: str = Query(...), db: Session = Depends(get_db)):
    try:
        qdate = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD).")
    
    # Find the winning session for this date
    session = (
        db.query(WinningSession)
        .filter(WinningSession.session_date == qdate)
        .order_by(WinningSession.uploaded_at.desc())
        .first()
    )
    if not session:
        return {"session_id": None, "files": [], "message": "No winning files for this date."}
    
    # Get all winning files for this session
    files = db.query(WinningFile).filter(WinningFile.session_id == session.id).all()
    
    result = []
    for wf in files:
        lt = db.query(LotteryType).filter_by(code=wf.lottery_code).first()
        result.append({
            "lottery_code": wf.lottery_code,
            "lottery_name": lt.name if lt else wf.lottery_code,  # full name
            "draw_number": wf.draw_number,
            "record_count": wf.record_count,
            "total_price": wf.total_price
        })
    
    return {
        "session_id": session.id,
        "files": result
    }