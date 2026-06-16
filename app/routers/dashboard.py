from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta
from app.database import get_db
from app.models import Agent, Order, Assignment, AgentSplit, Session, LotteryType

router = APIRouter()

@router.get("/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Return real-time stats for the dashboard."""
    
    # Total agents
    total_agents = db.query(Agent).count()
    
    # Total orders (all time)
    total_orders = db.query(Order).count()
    
    # Total tickets ordered
    total_tickets = db.query(func.sum(Order.quantity)).scalar() or 0
    
    # Recent draw date (latest order date)
    latest_order = db.query(Order).order_by(Order.order_date.desc()).first()
    recent_draw_date = latest_order.order_date.isoformat() if latest_order else None
    
    # Total splits completed
    total_splits = db.query(AgentSplit).count()
    
    # Today's uploads
    today = date.today()
    today_uploads = db.query(Session).filter(
        Session.session_date == today
    ).count()
    
    # Pending assignments (orders without complete assignment for latest date)
    pending = 0
    if recent_draw_date:
        orders = db.query(Order).filter(Order.order_date == recent_draw_date).all()
        assignments = db.query(Assignment).filter(Assignment.assignment_date == recent_draw_date).all()
        total_ordered = sum(o.quantity for o in orders)
        total_assigned = sum(a.assigned_count for a in assignments)
        pending = total_ordered - total_assigned
    
    # Recent activity (last 5 splits)
    recent_splits = db.query(AgentSplit).order_by(AgentSplit.created_at.desc()).limit(5).all()
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
    
    return {
        "total_agents": total_agents,
        "total_orders": total_orders,
        "total_tickets": total_tickets,
        "recent_draw_date": recent_draw_date,
        "total_splits": total_splits,
        "today_uploads": today_uploads,
        "pending_assignments": pending,
        "recent_activity": recent_activity
    }