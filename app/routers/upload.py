import os
import shutil
import tempfile
import uuid
import logging
from datetime import datetime, date as dateType
from typing import Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Query, Form
from sqlalchemy.orm import Session
from app.config import MAX_UPLOAD_SIZE, EXPECTED_DBF_COUNT, ALLOWED_EXTENSIONS, STORAGE_BASE
from app.database import get_db
from app.utils.archive_handler import extract_archive, is_valid_archive
from app.utils.dbf_handler import process_dbf_files
from app.models import Session as DbSession, LotteryFile, LotteryType, Order   # ← added Order

router = APIRouter()
logger = logging.getLogger(__name__)


def extract_date_from_zip_filename(filename: str):
    """Try to extract a YYYY-MM-DD date from a filename like '2026 06 05 DBS.zip'."""
    parts = filename.replace('.zip', '').replace('.ZIP', '').split()
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        try:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        except:
            pass
    return None


@router.post("/upload-dbf-archive")
async def upload_dbf_archive(
    file: UploadFile = File(...),
    date: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload a ZIP/RAR containing exactly 8 DBF files, store them, and link to a date."""
    # --- 1. Basic validation (unchanged) ---
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")
    if file.size and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_UPLOAD_SIZE // (1024*1024)} MB.")

    original_filename = file.filename or "unknown"
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid file type '{ext}'.")

    # --- 2. Save uploaded archive to temp ---
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            archive_path = tmp_file.name
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    tmp_dir = tempfile.mkdtemp(prefix="dbf_extract_")
    session_id = str(uuid.uuid4())
    session_storage = os.path.join(STORAGE_BASE, session_id)

    try:
        # --- 3. Validate & extract archive ---
        if not is_valid_archive(archive_path):
            raise HTTPException(status_code=400, detail="Invalid ZIP or RAR archive.")
        extract_archive(archive_path, tmp_dir)

        # --- 4. Process DBF files (counts, serials) ---
        lottery_list = process_dbf_files(tmp_dir, expected_count=EXPECTED_DBF_COUNT)

        # --- NEW: Validate draw numbers against orders for the given date ---
        if date:
            try:
                selected_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD).")

            orders = db.query(Order).filter(Order.order_date == selected_date).all()
            if not orders:
                raise HTTPException(status_code=400, detail=f"No orders found for {date}. Please enter orders first.")

            order_draws = {o.lottery_code: o.draw_number for o in orders}
            mismatches = []
            for lt in lottery_list:
                code = lt["lottery_name"]       # short code extracted from filename
                draw = lt["draw_number"]
                expected = order_draws.get(code)
                if expected is None:
                    mismatches.append(f"{code} (draw {draw}) not in today's orders")
                elif draw != expected:
                    mismatches.append(f"{code}: expected draw {expected}, but file has draw {draw}")

            if mismatches:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Draw numbers in the uploaded files do not match the orders for {date}. "
                        + "; ".join(mismatches)
                    )
                )
        # --- END validation ---

        # --- 5. Persist DBF files to session storage ---
        os.makedirs(session_storage, exist_ok=True)
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith('.dbf'):
                    src = os.path.join(root, f)
                    dst = os.path.join(session_storage, f)
                    shutil.copy2(src, dst)

        # --- 6. Extract date from ZIP filename ---
        zip_date_str = extract_date_from_zip_filename(original_filename)
        session_date = None
        if zip_date_str:
            try:
                session_date = datetime.strptime(zip_date_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        # --- 7. Store session and lottery file records in DB ---
        session_obj = DbSession(
            id=session_id,
            original_filename=original_filename,
            session_date=session_date
        )
        db.add(session_obj)

        for lt in lottery_list:
            db.add(LotteryFile(
                session_id=session_id,
                lottery_name=lt["lottery_name"],
                draw_number=lt["draw_number"],
                original_filename=lt["file_name"],
                record_count=lt["record_count"],
                start_serial=lt["start_serial"],
                end_serial=lt["end_serial"],
                serial_field=lt["serial_field_used"],
                stored_path=os.path.join(session_storage, lt["file_name"])
            ))
        db.commit()

        return {
            "success": True,
            "session_id": session_id,
            "total_lotteries": len(lottery_list),
            "lotteries": lottery_list,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during upload")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
    finally:
        # Cleanup temp files
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ----------------------------------------------------------------------
# NEW ENDPOINTS for Split page
# ----------------------------------------------------------------------

@router.get("/sessions/by-date")
def get_session_by_date(date: str = Query(...), db: Session = Depends(get_db)):
    """Return the most recent session_id for a given date, or null."""
    try:
        qdate = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD).")
    try:
        session = (
            db.query(DbSession)
            .filter(DbSession.session_date == qdate)
            .order_by(DbSession.uploaded_at.desc())
            .first()
        )
        return {"session_id": session.id if session else None}
    except Exception as e:
        logger.error(f"Database query error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/sessions/{session_id}/lotteries")
def get_session_lotteries(session_id: str, db: Session = Depends(get_db)):
    """Return all lottery files attached to a session."""
    sess = db.query(DbSession).filter(DbSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    lotteries = db.query(LotteryFile).filter(LotteryFile.session_id == session_id).all()
    result = []
    for lf in lotteries:
        lt = db.query(LotteryType).filter_by(code=lf.lottery_name).first()
        result.append({
            "lottery_name": lf.lottery_name,
            "draw_number": lf.draw_number,
            "record_count": lf.record_count,
            "start_serial": lf.start_serial,
            "end_serial": lf.end_serial,
        })
    return result