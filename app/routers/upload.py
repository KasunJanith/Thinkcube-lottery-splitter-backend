import os
import shutil
import tempfile
import uuid
import logging
from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from app.config import MAX_UPLOAD_SIZE, EXPECTED_DBF_COUNT, ALLOWED_EXTENSIONS, STORAGE_BASE
from app.utils.archive_handler import extract_archive, is_valid_archive
from app.utils.dbf_handler import process_dbf_files

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Response Models ---
class LotteryInfo(BaseModel):
    lottery_name: str
    draw_number: str
    file_name: str
    record_count: int
    serial_field_used: str | None = None
    start_serial: str | None = None
    end_serial: str | None = None


class UploadResponse(BaseModel):
    success: bool
    session_id: str
    total_lotteries: int
    lotteries: list[LotteryInfo]


# --- Endpoint ---
@router.post("/upload-dbf-archive", response_model=UploadResponse)
async def upload_dbf_archive(file: UploadFile = File(...)):
    """
    Upload a ZIP/RAR archive containing exactly 8 DBF files.
    Files must be named like: <lottery_name><draw_number>.dbf
    Returns identification, record count, serial range, and a session ID.
    """
    # 1. Basic validation
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")
    if file.size and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max allowed size is {MAX_UPLOAD_SIZE // (1024*1024)} MB.",
        )

    original_filename = file.filename or "unknown"
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Only {', '.join(ALLOWED_EXTENSIONS)} are allowed.",
        )

    # 2. Save uploaded archive to a temporary file
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            archive_path = tmp_file.name
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # 3. Temporary extraction directory + session storage
    tmp_dir = tempfile.mkdtemp(prefix="dbf_extract_")
    session_id = str(uuid.uuid4())
    session_storage = os.path.join(STORAGE_BASE, session_id)

    try:
        # 4. Validate archive and extract
        if not is_valid_archive(archive_path):
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP or RAR archive.")
        extract_archive(archive_path, tmp_dir)

        # 5. Process DBF files (validation, record counts, serial ranges)
        lottery_list = process_dbf_files(tmp_dir, expected_count=EXPECTED_DBF_COUNT)

        # 6. Persist DBF files to session storage for later splitting
        os.makedirs(session_storage, exist_ok=True)
        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith('.dbf'):
                    src = os.path.join(root, f)
                    dst = os.path.join(session_storage, f)
                    shutil.copy2(src, dst)

        # 7. Return success
        return UploadResponse(
            success=True,
            session_id=session_id,
            total_lotteries=len(lottery_list),
            lotteries=lottery_list,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during archive processing")
        raise HTTPException(status_code=500, detail=f"Internal processing error: {str(e)}")
    finally:
        # Cleanup temporary files
        try:
            if os.path.exists(archive_path):
                os.unlink(archive_path)
        except Exception as e:
            logger.warning(f"Could not delete temp archive {archive_path}: {e}")
        try:
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Could not delete temp directory {tmp_dir}: {e}")