from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from datetime import date
from app.database import get_db
from app.models import Assignment, Order, Agent, LotteryType

router = APIRouter()

class AgentAssignmentItem(BaseModel):
    lottery_code: str
    agent_name: str
    count: int

class AssignmentRequest(BaseModel):
    assignment_date: date
    assignments: List[AgentAssignmentItem]

@router.post("/assignments")
def save_assignments(request: AssignmentRequest, db: Session = Depends(get_db)):
    # Delete existing assignments for that date
    db.query(Assignment).filter(Assignment.assignment_date == request.assignment_date).delete()
    for item in request.assignments:
        agent = db.query(Agent).filter_by(name=item.agent_name).first()
        if not agent:
            raise HTTPException(400, f"Agent {item.agent_name} not found")
        # Optionally check that order exists and total assigned <= quantity
        assignment = Assignment(
            assignment_date=request.assignment_date,
            lottery_code=item.lottery_code,
            agent_id=agent.id,
            assigned_count=item.count
        )
        db.add(assignment)
    db.commit()
    return {"status": "saved"}

@router.get("/assignments/{assignment_date}")
def get_assignments(assignment_date: date, db: Session = Depends(get_db)):
    assignments = db.query(Assignment).filter(Assignment.assignment_date == assignment_date).all()
    agents = db.query(Agent).all()
    lottery_types = db.query(LotteryType).all()
    orders = db.query(Order).filter(Order.order_date == assignment_date).all()
    # Build response: for each lottery, show available quantity and per-agent assigned
    result = []
    for lt in lottery_types:
        order = next((o for o in orders if o.lottery_code == lt.code), None)
        available = order.quantity if order else 0
        agent_counts = {}
        for agent in agents:
            ass = next((a for a in assignments if a.lottery_code == lt.code and a.agent_id == agent.id), None)
            agent_counts[agent.name] = ass.assigned_count if ass else 0
        total_assigned = sum(agent_counts.values())
        result.append({
            "lottery_code": lt.code,
            "lottery_name": lt.name,
            "draw_number": order.draw_number if order else "",
            "available_quantity": available,
            "agent_counts": agent_counts,
            "remaining": available - total_assigned
        })
    return result