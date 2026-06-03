from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from app.database import get_db
from app.models import Order, LotteryType

router = APIRouter()

class OrderItem(BaseModel):
    lottery_code: str
    draw_number: str
    quantity: int

class OrderRequest(BaseModel):
    order_date: date
    orders: List[OrderItem]

@router.post("/orders")
def save_orders(request: OrderRequest, db: Session = Depends(get_db)):
    # Delete existing orders for that date
    db.query(Order).filter(Order.order_date == request.order_date).delete()
    for item in request.orders:
        # Verify lottery code exists
        lt = db.query(LotteryType).filter_by(code=item.lottery_code).first()
        if not lt:
            raise HTTPException(400, f"Invalid lottery code: {item.lottery_code}")
        order = Order(
            order_date=request.order_date,
            lottery_code=item.lottery_code,
            draw_number=item.draw_number,
            quantity=item.quantity
        )
        db.add(order)
    db.commit()
    return {"status": "saved"}

@router.get("/orders/{order_date}")
def get_orders(order_date: date, db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.order_date == order_date).all()
    # If no orders, return empty list with lottery types so frontend can build table
    lottery_types = db.query(LotteryType).all()
    result = []
    for lt in lottery_types:
        order = next((o for o in orders if o.lottery_code == lt.code), None)
        result.append({
            "lottery_code": lt.code,
            "lottery_name": lt.name,
            "draw_number": order.draw_number if order else "",
            "quantity": order.quantity if order else 0
        })
    return result