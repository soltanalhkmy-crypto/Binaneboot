from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from app.db.database import get_db
from app.db.models import User, Settings, Trade
from app.api.auth import verify_password, create_access_token, get_password_hash, ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY, ALGORITHM
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

class Token(BaseModel):
    access_token: str
    token_type: str

class SettingsUpdate(BaseModel):
    target_funding_rate: float
    entry_time_minutes: int
    exit_safe_seconds: int
    trade_amount: float
    bot_active: bool

class CredentialsUpdate(BaseModel):
    new_username: str
    new_password: str

class TradeResponse(BaseModel):
    id: int
    symbol: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    spot_entry_price: float
    futures_entry_price: float
    spot_exit_price: Optional[float] = None
    futures_exit_price: Optional[float] = None
    amount: float
    profit_usdt: Optional[float] = None
    status: str
    error_message: Optional[str] = None

    class Config:
        from_attributes = True

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(Settings).first()
    return settings

@router.put("/settings")
def update_settings(settings_update: SettingsUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(Settings).first()
    settings.target_funding_rate = settings_update.target_funding_rate
    settings.entry_time_minutes = settings_update.entry_time_minutes
    settings.exit_safe_seconds = settings_update.exit_safe_seconds
    settings.trade_amount = settings_update.trade_amount
    settings.bot_active = settings_update.bot_active
    db.commit()
    return {"status": "success"}

@router.get("/trades", response_model=List[TradeResponse])
def get_trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trades = db.query(Trade).order_by(Trade.entry_time.desc()).all()
    return trades

@router.post("/toggle_bot")
def toggle_bot(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(Settings).first()
    settings.bot_active = not settings.bot_active
    db.commit()
    return {"bot_active": settings.bot_active}

@router.put("/credentials")
def update_credentials(creds_update: CredentialsUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.username = creds_update.new_username
    if creds_update.new_password:
        current_user.hashed_password = get_password_hash(creds_update.new_password)
    db.commit()
    return {"status": "success"}
