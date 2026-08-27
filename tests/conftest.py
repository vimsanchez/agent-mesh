"""Configuración de pruebas.

El entorno se fija ANTES de importar cualquier cosa de `app`, porque
`app.db.session` construye el engine al importarse. Las variables reales del
proceso tienen prioridad sobre `.env`, así que un `.env` local no contamina.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="agent-mesh-tests-"))

os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["ADMIN_EMAIL_DOMAIN"] = "empresa-interna.test"
os.environ["PUBLIC_SERVICE_DOMAIN"] = "mesh.otrodominio.test"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@empresa-interna.test"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session as SASession  # noqa: E402

# Importar app.db.session registra el listener que activa PRAGMA foreign_keys.
# Sin él las FK no se aplican en SQLite y las pruebas de integridad mentirían.
import app.db.session  # noqa: E402, F401
from app.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def tmp_db_url() -> str:
    """URL de una base vacía y desechable, para pruebas de migración."""
    path = Path(tempfile.mkdtemp(prefix="agent-mesh-migr-")) / "m.db"
    return f"sqlite:///{path}"


def alembic_config(db_url: str) -> Config:
    """Config de Alembic apuntando a una base concreta.

    `migrations/env.py` respeta la URL que se le fije aquí; solo cae a Settings
    cuando nadie la puso.
    """
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.fixture
def migrated_engine(tmp_db_url: str) -> Iterator[Engine]:
    """Base con el esquema aplicado **por la migración**, no por create_all.

    Es deliberado: así lo que se prueba es la migración real que va a correr en
    el contenedor, y no una versión paralela del esquema generada desde los
    modelos. Si ambas divergen, estas pruebas lo notan.
    """
    command.upgrade(alembic_config(tmp_db_url), "head")
    engine = create_engine(tmp_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[SASession]:
    with SASession(migrated_engine) as session:
        yield session
