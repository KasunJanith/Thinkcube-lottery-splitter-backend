from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime
from app.database import get_db
from app.models import Agent, Order, Assignment, AgentSplit, Session, LotteryType, LotteryFile

router = APIRouter()

@router.get("/dashboard/stats")
def get_dashboard_stats(
    date_param: str = Query(None, alias="date"),
    db: Session = Depends(get_db)
):
    """
    Return dashboard stats.
    If date is provided, show stats for that date.
    If not, show today's stats.
    """
    # Parse date or use today
    if date_param:
        try:
            selected_date = datetime.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()
    
    # ---- Always-global stats ----
    total_agents = db.query(Agent).count()
    
    # ---- Date-specific stats ----
    
    # Orders for selected date
    orders = db.query(Order).filter(Order.order_date == selected_date).all()
    total_lotteries_with_orders = len(orders)
    total_tickets_ordered = sum(o.quantity for o in orders)
    
    # Draw numbers (one per lottery)
    draw_numbers = {}
    for o in orders:
        lt = db.query(LotteryType).filter_by(code=o.lottery_code).first()
        draw_numbers[o.lottery_code] = {
            "lottery_name": lt.name if lt else o.lottery_code,
            "draw_number": o.draw_number
        }
    
    # Assignments for selected date
    assignments = db.query(Assignment).filter(
        Assignment.assignment_date == selected_date
    ).all()
    total_assigned = sum(a.assigned_count for a in assignments)
    
    # Per-agent assigned
    agents = db.query(Agent).all()
    agent_assignments = {}
    for agent in agents:
        agent_total = sum(a.assigned_count for a in assignments if a.agent_id == agent.id)
        agent_assignments[agent.name] = agent_total
    
    remaining_to_assign = total_tickets_ordered - total_assigned
    
    # Upload session for selected date
    session = db.query(Session).filter(
        Session.session_date == selected_date
    ).order_by(Session.uploaded_at.desc()).first()
    
    upload_exists = session is not None
    session_id = session.id if session else None
    
    # Uploaded file details
    uploaded_files = []
    total_uploaded_records = 0
    if session:
        lottery_files = db.query(LotteryFile).filter(
            LotteryFile.session_id == session.id
        ).all()
        for lf in lottery_files:
            lt = db.query(LotteryType).filter_by(code=lf.lottery_name).first()
            uploaded_files.append({
                "lottery_code": lf.lottery_name,
                "lottery_name": lt.name if lt else lf.lottery_name,
                "draw_number": lf.draw_number,
                "record_count": lf.record_count,
                "matches_order": False  # will be checked below
            })
            total_uploaded_records += lf.record_count
    
    # Check mismatches between uploaded records and ordered quantities
    mismatches = []
    for uf in uploaded_files:
        order = next((o for o in orders if o.lottery_code == uf["lottery_code"]), None)
        if order:
            uf["ordered_quantity"] = order.quantity
            uf["matches_order"] = uf["record_count"] == order.quantity
            if not uf["matches_order"]:
                mismatches.append({
                    "lottery": uf["lottery_name"],
                    "ordered": order.quantity,
                    "uploaded": uf["record_count"]
                })
    
    # Splits for selected date
    splits_query = db.query(AgentSplit).join(
        Session, AgentSplit.session_id == Session.id
    ).filter(
        Session.session_date == selected_date
    )
    total_splits = splits_query.count()
    splits_data = splits_query.all()
    
    # Splits per agent
    splits_per_agent = {}
    for agent in agents:
        agent_splits = [s for s in splits_data if s.agent_id == agent.id]
        splits_per_agent[agent.name] = {
            "count": len(agent_splits),
            "total_records": sum(s.record_count for s in agent_splits)
        }
    
    # Recent activity (last 5 splits across all dates)
    recent_splits = db.query(AgentSplit).order_by(
        AgentSplit.created_at.desc()
    ).limit(5).all()
    recent_activity = []
    for split in recent_splits:
        agent = db.query(Agent).filter(Agent.id == split.agent_id).first()
        lt = db.query(LotteryType).filter(LotteryType.code == split.lottery_code).first()
        recent_activity.append({
            "agent": agent.name if agent else "Unknown",
            "lottery": lt.name if lt else split.lottery_code,
            "draw": split.draw_number,
            "records": split.record_count,
            "date": split.created_at.strftime("%d/%m/%Y %H:%M") if split.created_at else ""
        })
    
    # Latest order date (for date picker default)
    latest_order = db.query(Order).order_by(Order.order_date.desc()).first()
    latest_order_date = latest_order.order_date.isoformat() if latest_order else None
    
    return {
        "selected_date": selected_date.isoformat(),
        "latest_order_date": latest_order_date,
        
        # Always-global
        "total_agents": total_agents,
        
        # Date-specific - Orders
        "total_lotteries_with_orders": total_lotteries_with_orders,
        "total_tickets_ordered": total_tickets_ordered,
        "draw_numbers": list(draw_numbers.values()),
        
        # Date-specific - Assignments
        "total_assigned": total_assigned,
        "agent_assignments": agent_assignments,
        "remaining_to_assign": remaining_to_assign,
        
        # Date-specific - Upload
        "upload_exists": upload_exists,
        "session_id": session_id,
        "uploaded_files_count": len(uploaded_files),
        "total_uploaded_records": total_uploaded_records,
        "mismatches": mismatches,
        "has_mismatches": len(mismatches) > 0,
        
        # Date-specific - Splits
        "total_splits": total_splits,
        "splits_per_agent": splits_per_agent,
        
        # Recent activity (all dates)
        "recent_activity": recent_activity
    }