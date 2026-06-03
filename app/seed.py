from app.database import SessionLocal, engine
from app.models import Base, LotteryType, Agent

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Seed lottery types
    lotteries = [
        ("ada", "Ada Sampatha"),
        ("dana", "Dhana Nidhanaya"),
        ("govi", "Govi Setha"),
        ("hada", "Handahana"),
        ("jaya", "NLB Jaya"),
        ("maha", "Mahajana Sampatha"),
        ("mgap", "Mega Power"),
        ("suba", "Suba Dawasak"),
    ]
    for code, name in lotteries:
        if not db.query(LotteryType).filter_by(code=code).first():
            db.add(LotteryType(code=code, name=name))
    # Seed agents
    agents = ["JAYAWAY", "WINWAY"]
    for name in agents:
        if not db.query(Agent).filter_by(name=name).first():
            db.add(Agent(name=name))
    db.commit()
    db.close()