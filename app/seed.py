from app.database import SessionLocal, engine
from app.models import Base, LotteryType, Agent, DrawNumberBase
from datetime import date

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Seed lottery types
    lotteries = [
        ("ada", "Ada Sampatha"),
        ("dana", "Dhana Nidhanaya"),
        ("GOVI", "Govi Setha"),
        ("HADA", "Handahana"),
        ("Jaya", "NLB Jaya"),
        ("Maha", "Mahajana Sampatha"),
        ("mgap", "Mega Power"),
        ("SUBA", "Suba Dawasak"),
    ]
    for code, name in lotteries:
        if not db.query(LotteryType).filter_by(code=code).first():
            db.add(LotteryType(code=code, name=name))
    # Seed agents
    agents = ["JAYAWAY", "WINWAY"]
    for name in agents:
        if not db.query(Agent).filter_by(name=name).first():
            db.add(Agent(name=name))
            
    # Seed draw number bases for June 1, 2026
    draw_bases = [
        ("ada", date(2026,6,1), "0780"),
        ("dana", date(2026,6,1), "2235"),
        ("GOVI", date(2026,6,1), "4447"),
        ("HADA", date(2026,6,1), "1514"),
        ("Jaya", date(2026,6,1), "0473"),
        ("Maha", date(2026,6,1), "6205"),
        ("mgap", date(2026,6,1), "2553"),
        ("SUBA", date(2026,6,1), "0321"),
    ]
    for code, bdate, bnumber in draw_bases:
        existing = db.query(DrawNumberBase).filter_by(lottery_code=code).first()
        if not existing:
            db.add(DrawNumberBase(lottery_code=code, base_date=bdate, base_draw_number=bnumber))        
    db.commit()
    db.close()