from fastapi import FastAPI

from app.core.config import settings
from app.modules.events.router import router as events_router

app = FastAPI(title=settings.app_name)
app.include_router(events_router, prefix="/api/v1")
