import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import STORAGE_BASE
from app.utils.dbf_splitter import split_dbf

router = APIRouter()
logger = logging.getLogger(__name__)


class SplitRequest(BaseModel):
    session_id: str
    lottery_name: str
    draw_number: str
    agent_count: int = 2                     # default 2
    portion_size: int | None = None         # if None → auto equal portion


class SplitPart(BaseModel):
    part_number: int
    start_serial: str
    end_serial: str
    record_count: int
    saved_file: str


class SplitResponse(BaseModel):
    success: bool
    original_file: str
    parts: list[SplitPart]


@router.post("/split", response_model=SplitResponse)
def split_lottery_file(request: SplitRequest):
    """
    Split a specific lottery DBF (session_id, lottery_name, draw_number)
    into parts according to agent_count and portion_size.
    Each part is saved as a new DBF file in the session folder.
    """
    # Build path to the original DBF file
    filename = f"{request.lottery_name}{request.draw_number}.dbf"
    file_path = os.path.join(STORAGE_BASE, request.session_id, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"DBF file not found: {filename}")

    try:
        parts = split_dbf(
            file_path=file_path,
            agent_count=request.agent_count,
            portion_size=request.portion_size,
            session_id=request.session_id,
            lottery_name=request.lottery_name,
            draw_number=request.draw_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Split failed")
        raise HTTPException(status_code=500, detail=f"Split error: {str(e)}")

    return SplitResponse(
        success=True,
        original_file=filename,
        parts=parts,
    )