from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.events import router as events_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(events_router)

__all__ = ["api_v1_router"]
