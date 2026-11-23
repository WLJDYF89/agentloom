from __future__ import annotations

from fastapi import APIRouter

from app.api.ops import router as ops_router

__all__ = ["api_router", "ops_router"]


def build_api_router() -> APIRouter:
    from app.api.v1 import api_v1_router

    router = APIRouter()
    router.include_router(ops_router)
    router.include_router(api_v1_router)
    return router
