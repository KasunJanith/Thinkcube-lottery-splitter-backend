from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from app.database import get_db
from app.models import DrawNumberBase, Order, LotteryType

router = APIRouter()

class OrderItem(BaseModel):
    lottery_code: str
    draw_number: str
    quantity: int

class OrderRequest(BaseModel):
    order_date: date
    orders: List[OrderItem]

# IMPORTANT: static routes before dynamic ones
@router.get("/orders/latest")
def get_latest_order_date(db: Session = Depends(get_db)):
    latest_order = db.query(Order).order_by(Order.order_date.desc()).first()
    if not latest_order:
        return {"date": None}
    return {"date": latest_order.order_date.isoformat()}

@router.get("/orders/{order_date}")
def get_orders(order_date: date, db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.order_date == order_date).all()
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

@router.post("/orders")
def save_orders(request: OrderRequest, db: Session = Depends(get_db)):
    db.query(Order).filter(Order.order_date == request.order_date).delete()
    for item in request.orders:
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

@router.get("/draw-numbers/{order_date}")
def get_draw_numbers(order_date: date, db: Session = Depends(get_db)):
    bases = db.query(DrawNumberBase).all()
    result = []
    for base in bases:
        diff_days = (order_date - base.base_date).days
        # convert base draw number to int, add diff, then zero-pad to same length
        try:
            num = int(base.base_draw_number) + diff_days
            padded = str(num).zfill(len(base.base_draw_number))
        except ValueError:
            padded = base.base_draw_number  # fallback
        result.append({
            "lottery_code": base.lottery_code,
            "draw_number": padded
        })
    return result