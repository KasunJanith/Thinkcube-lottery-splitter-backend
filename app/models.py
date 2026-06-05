from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import date, datetime


class LotteryType(Base):
    __tablename__ = "lottery_types"
    code = Column(String(10), primary_key=True)
    name = Column(String(100), nullable=False)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_date = Column(Date, nullable=False)
    lottery_code = Column(String(10), ForeignKey("lottery_types.code"), nullable=False)
    draw_number = Column(String(20), nullable=False)
    quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    lottery_type = relationship("LotteryType")


class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_date = Column(Date, nullable=False)
    lottery_code = Column(String(10), ForeignKey("lottery_types.code"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    assigned_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    lottery_type = relationship("LotteryType")
    agent = relationship("Agent")


class DrawNumberBase(Base):
    __tablename__ = "draw_number_base"
    lottery_code = Column(String(10), ForeignKey("lottery_types.code"), primary_key=True)
    base_date = Column(Date, nullable=False)
    base_draw_number = Column(String(20), nullable=False)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String(36), primary_key=True)
    original_filename = Column(String(255))
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="extracted")
    session_date = Column(Date, nullable=True)


class LotteryFile(Base):
    __tablename__ = "lottery_files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"))
    lottery_name = Column(String(50))
    draw_number = Column(String(20))
    original_filename = Column(String(100))
    record_count = Column(Integer)
    start_serial = Column(String(11))
    end_serial = Column(String(11))
    serial_field = Column(String(20))
    stored_path = Column(String(500))


class AgentSplit(Base):
    __tablename__ = "agent_splits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id"))
    agent_id = Column(Integer, ForeignKey("agents.id"))
    lottery_code = Column(String(10), ForeignKey("lottery_types.code"))
    draw_number = Column(String(20))
    start_serial = Column(String(11))
    end_serial = Column(String(11))
    record_count = Column(Integer)
    saved_file_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)