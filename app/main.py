"""Composición de la aplicación.

Un solo proceso FastAPI sirve la API de agentes (`/api/v1`) y el panel (`/admin`),
expuesto por un único puerto detrás del túnel de Cloudflare (SPEC.md §4).
"""

import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="Agent Mesh",
        version="0.1.0",
        description=(
            "Mensajería asíncrona y conocimiento compartido entre sesiones de "
            "agentes de codificación. Enrutador determinista: sin LLMs dentro."
        ),
    )
    app.include_router(health_router)
    return app


app = create_app()
