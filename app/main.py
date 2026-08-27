"""Composición de la aplicación.

Un solo proceso FastAPI sirve la API de agentes (`/api/v1`) y el panel (`/admin`),
expuesto por un único puerto detrás del túnel de Cloudflare (SPEC.md §4).
"""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.admin.deps import RedirectToLoginError
from app.admin.routes import router as admin_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.v1.router import router as api_v1_router
from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services import identity

logger = logging.getLogger("agent_mesh")


def _run_bootstrap(settings: Settings) -> None:
    """Crea el administrador inicial si no hay ninguno (SPEC §9).

    La contraseña se imprime **una sola vez** aquí y en ningún otro lado: no se
    guarda, no se devuelve por la API y la cuenta queda obligada a cambiarla.
    Es idempotente, así que reiniciar el contenedor no genera credenciales
    nuevas ni pisa las existentes.
    """
    with SessionLocal() as db:
        try:
            result = identity.bootstrap_admin(db, settings)
        except Exception:
            db.rollback()
            logger.exception("falló el bootstrap del administrador inicial")
            return
        if result is None:
            logger.info("bootstrap: ya existe al menos un administrador, no se crea otro")
            return
        admin, password = result
        db.commit()

    logger.warning(
        "\n"
        "==============================================================\n"
        " ADMINISTRADOR INICIAL CREADO\n"
        "   correo:     %s\n"
        "   contraseña: %s\n"
        " Esta contraseña se muestra UNA SOLA VEZ y hay que cambiarla al\n"
        " entrar. Cualquiera que pueda leer este log la conoce.\n"
        "==============================================================",
        admin.email,
        password,
    )


def _resolve_secret_key(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    logger.warning(
        "SECRET_KEY no está configurada: se genera una al azar. Las sesiones del "
        "panel se cerrarán en cada reinicio. Fíjala en el entorno para evitarlo."
    )
    return secrets.token_urlsafe(48)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _run_bootstrap(settings)
        yield

    app = FastAPI(
        title="Agent Mesh",
        version="0.1.0",
        description=(
            "Mensajería asíncrona y conocimiento compartido entre sesiones de "
            "agentes de codificación. Enrutador determinista: sin LLMs dentro."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=_resolve_secret_key(settings),
        session_cookie="mesh_admin",
        same_site="lax",
        # El servicio va detrás del túnel de Cloudflare, que termina TLS, así que
        # el navegador siempre habla https aunque el contenedor reciba http.
        https_only=True,
    )

    @app.exception_handler(RedirectToLoginError)
    async def _to_login(_request: Request, exc: RedirectToLoginError) -> RedirectResponse:
        return RedirectResponse(url=exc.to, status_code=303)

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(api_v1_router)
    app.include_router(admin_router)
    return app


app = create_app()
