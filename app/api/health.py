"""Healthcheck. No pertenece a la API de agentes, por eso vive fuera de /api/v1."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/healthz", response_model=Health)
def healthz(db: Annotated[Session, Depends(get_db)]) -> Health:
    """Comprueba que el proceso responde y que la base de datos contesta."""
    db.execute(text("SELECT 1"))
    return Health(status="ok", database="ok")
