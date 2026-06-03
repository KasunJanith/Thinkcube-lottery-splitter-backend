from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import os
from app.utils.dbf_splitter import split_dbf_by_agents
from app.config import STORAGE_BASE

router = APIRouter()


class AgentAssignment(BaseModel):
    agent_name: str
    count: int


class SplitRequest(BaseModel):
    session_id: str
    lottery_name: str
    draw_number: str
    assignments: List[AgentAssignment]


class SplitPart(BaseModel):
    part_number: int
    start_serial: str
    end_serial: str
    record_count: int
    saved_file: str
    agent: str


class SplitResponse(BaseModel):
    success: bool
    original_file: str
    parts: List[SplitPart]
    total_records: int
    assigned_records: int
    remaining_records: int


@router.post("/split", response_model=SplitResponse)
def split_lottery_file(request: SplitRequest):
    filename = f"{request.lottery_name}{request.draw_number}.dbf"
    file_path = os.path.join(STORAGE_BASE, request.session_id, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"DBF file not found: {filename}")

    try:
        result = split_dbf_by_agents(
            file_path=file_path,
            assignments=[(a.agent_name, a.count) for a in request.assignments],
            session_id=request.session_id,
            lottery_name=request.lottery_name,
            draw_number=request.draw_number,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))