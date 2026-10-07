from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from app.db.database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    target_funding_rate = Column(Float, default=0.15) # In percentage
    entry_time_minutes = Column(Integer, default=15) # Minutes before funding
    exit_safe_seconds = Column(Integer, default=3) # Seconds after funding
    trade_amount = Column(Float, default=100.0) # Fixed USDT amount
    bot_active = Column(Boolean, default=False)

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    spot_entry_price = Column(Float)
    futures_entry_price = Column(Float)
    spot_exit_price = Column(Float, nullable=True)
    futures_exit_price = Column(Float, nullable=True)
    amount = Column(Float)
    profit_usdt = Column(Float, nullable=True)
    status = Column(String, default="open") # "open", "closed", "failed"
    error_message = Column(String, nullable=True)
