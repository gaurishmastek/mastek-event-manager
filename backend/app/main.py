from fastapi import FastAPI

from app.core.config import settings
from app.modules.events.router import router as events_router
from app.modules.gate.router import router as gate_router
from app.modules.guests.router import router as guests_router

app = FastAPI(title=settings.app_name)
app.include_router(events_router, prefix="/api/v1")
app.include_router(guests_router, prefix="/api/v1")
app.include_router(gate_router, prefix="/api/v1")
