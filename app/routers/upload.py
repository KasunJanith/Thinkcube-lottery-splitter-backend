import os
import shutil
import tempfile
import logging
from typing import List
from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from app.config import MAX_UPLOAD_SIZE, EXPECTED_DBF_COUNT, ALLOWED_EXTENSIONS
from app.utils.archive_handler import extract_archive, is_valid_archive
from app.utils.dbf_handler import process_dbf_files

router = APIRouter()
logger = logging.getLogger(__name__)

# Response models
class LotteryInfo(BaseModel):
    lottery_name: str
    draw_number: str
    file_name: str
    record_count: int

class UploadResponse(BaseModel):
    success: bool
    total_lotteries: int
    lotteries: List[LotteryInfo]
    processing_time_seconds: float = 0.0

@router.post("/upload-dbf-archive", response_model=UploadResponse)
async def upload_dbf_archive(file: UploadFile = File(...)):
    """
    Upload a ZIP/RAR archive containing exactly 8 DBF files.
    Files must be named like: <lottery_name><draw_number>.dbf
    Returns identification and record count for each lottery.
    """
    import time
    start_time = time.time()

    # 1. Validate file presence and size
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")
    if file.size and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max allowed size is {MAX_UPLOAD_SIZE // (1024*1024)} MB.")

    # 2. Validate extension
    original_filename = file.filename or "unknown"
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid file type '{ext}'. Only {', '.join(ALLOWED_EXTENSIONS)} are allowed.")

    # 3. Save to temporary file
    suffix = ext
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            archive_path = tmp_file.name
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # Create temporary directory for extraction
    tmp_dir = tempfile.mkdtemp(prefix="dbf_extract_")
    try:
        # 4. Validate that it's a proper archive
        if not is_valid_archive(archive_path):
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP or RAR archive.")

        # 5. Extract all files to tmp_dir
        extract_archive(archive_path, tmp_dir)

        # 6. Process DBF files (collect, validate naming, count records)
        lottery_list = process_dbf_files(tmp_dir, expected_count=EXPECTED_DBF_COUNT)

        processing_time = time.time() - start_time
        return UploadResponse(
            success=True,
            total_lotteries=len(lottery_list),
            lotteries=lottery_list,
            processing_time_seconds=round(processing_time, 3)
        )

    except HTTPException:
        raise  # re-raise known HTTP exceptions
    except Exception as e:
        logger.exception("Unexpected error during archive processing")
        raise HTTPException(status_code=500, detail=f"Internal processing error: {str(e)}")
    finally:
        # Cleanup: remove temporary archive and extracted directory
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