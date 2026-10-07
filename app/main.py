from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from app.api.endpoints import router as api_router
from app.bot.trading_bot import bot_instance
import threading
import os
from app.db.database import engine, Base, SessionLocal
from app.db.models import User, Settings
from app.api.auth import get_password_hash

app = FastAPI(title="Binance Funding Bot API")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Initialize database
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    if not db.query(User).first():
        admin = User(username=os.getenv('ADMIN_USERNAME', 'admin'), hashed_password=get_password_hash(os.getenv('ADMIN_PASSWORD', 'admin')))
        db.add(admin)
    if not db.query(Settings).first():
        settings = Settings()
        db.add(settings)
    db.commit()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

@app.on_event("startup")
def startup_event():
    # Start the bot in a background thread
    bot_thread = threading.Thread(target=bot_instance.start, daemon=True)
    bot_thread.start()

@app.on_event("shutdown")
def shutdown_event():
    bot_instance.stop()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")
