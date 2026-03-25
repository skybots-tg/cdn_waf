"""Analytics API — aggregates sub-routers for global and per-domain analytics."""
from fastapi import APIRouter

from app.api.v1.analytics_global import router as global_router
from app.api.v1.analytics_domain import router as domain_router

router = APIRouter()
router.include_router(global_router)
router.include_router(domain_router)
