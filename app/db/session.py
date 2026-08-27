"""Engine y factoría de sesiones.

Regla 3 de `CLAUDE.md`: nada de SQL específico de SQLite. La única excepción
permitida son los `PRAGMA` de arranque de conexión que están más abajo, que son
configuración del motor y no consultas de dominio. Migrar a Postgres debe ser
cambiar `DATABASE_URL`.
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _build_engine() -> Engine:
    settings = get_settings()
    connect_args: dict[str, Any] = {}
    if settings.is_sqlite:
        # FastAPI atiende peticiones en varios hilos; la conexión se comparte.
        connect_args["check_same_thread"] = False
    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )


engine: Engine = _build_engine()


@event.listens_for(Engine, "connect")
def _configure_sqlite_connection(dbapi_connection: Any, _record: Any) -> None:
    """PRAGMA de arranque. Única excepción a la regla 3, y solo para SQLite.

    - `foreign_keys=ON`: SQLite ignora las FK por defecto, y sin esto el
      aislamiento por proyecto dependería solo del código de aplicación.
    - `journal_mode=WAL`: permite lecturas concurrentes mientras el long polling
      mantiene conexiones abiertas.
    - `busy_timeout`: en vez de fallar de inmediato ante un lock, espera. Importa
      para el reclamo atómico de mensajes.
    """
    if type(dbapi_connection).__module__.split(".")[0] != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesión de base de datos por petición."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
