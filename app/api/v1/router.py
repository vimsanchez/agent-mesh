"""Router de la API de agentes. Prefijo `/api/v1` (SPEC §8)."""

from fastapi import APIRouter

from app.api.v1.messages import router as messages_router
from app.api.v1.projects import router as projects_router
from app.api.v1.sessions import router as sessions_router

router = APIRouter(prefix="/api/v1")
router.include_router(projects_router)
router.include_router(sessions_router)
router.include_router(messages_router)
