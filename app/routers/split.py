from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import os, io, zipfile
from fastapi.responses import StreamingResponse
from app.database import get_db
from app.models import Session, LotteryFile, AgentSplit, Agent, Assignment, Order
from app.utils.dbf_splitter import split_single_lottery_for_agent
from app.config import STORAGE_BASE

router = APIRouter()

class SplitRequest(BaseModel):
    session_id: str
    agent_name: str
    assignment_date: str   # e.g., "2026-06-03"

@router.post("/split-for-agent")
def split_for_agent(request: SplitRequest, db: Session = Depends(get_db)):
    # Validate session exists
    session = db.query(Session).filter(Session.id == request.session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    # Find agent
    agent = db.query(Agent).filter(Agent.name == request.agent_name).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Get assignments for the date and agent
    assignments = db.query(Assignment).filter(
        Assignment.assignment_date == request.assignment_date,
        Assignment.agent_id == agent.id
    ).all()
    if not assignments:
        raise HTTPException(400, "No assignments found for this agent/date")

    # For each assignment, find the corresponding LotteryFile in the session
    # We need to match lottery_code and draw_number (from orders)
    # Orders for that date contain draw_number.
    orders = db.query(Order).filter(Order.order_date == request.assignment_date).all()
    if not orders:
        raise HTTPException(400, "No orders found for this date")

    results = []
    for assignment in assignments:
        # Find order to get draw_number
        order = next((o for o in orders if o.lottery_code == assignment.lottery_code), None)
        if not order:
            continue  # or raise error
        # Find the DBF file in the session with matching lottery name (code) and draw_number
        # Our lottery_files store lottery_name as original short name? In upload we parse filename and get lottery_name (the short code) and draw_number.
        # So we can match directly.
        dbf_file = db.query(LotteryFile).filter(
            LotteryFile.session_id == request.session_id,
            LotteryFile.lottery_name == assignment.lottery_code,
            LotteryFile.draw_number == order.draw_number
        ).first()
        if not dbf_file:
            raise HTTPException(400, f"DBF file not found for {assignment.lottery_code} draw {order.draw_number}")

        # Split that DBF file: take the first `assignment.assigned_count` records
        input_path = dbf_file.stored_path
        output_filename = f"{assignment.lottery_code}_{order.draw_number}_{agent.name}.dbf"
        output_dir = os.path.join(STORAGE_BASE, request.session_id, "splits")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        # Use a modified split function that returns the part details
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
        results.append(part_info)

    db.commit()
    return {"status": "split completed", "files": results}