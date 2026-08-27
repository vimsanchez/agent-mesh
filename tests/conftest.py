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
os.environ["SECRET_KEY"] = "clave-de-pruebas-no-secreta"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import Session as SASession  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# Importar app.db.session registra el listener que activa PRAGMA foreign_keys.
# Sin él las FK no se aplican en SQLite y las pruebas de integridad mentirían.
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402


def alembic_config(db_url: str) -> Config:
    """Config de Alembic apuntando a una base concreta.

    `migrations/env.py` respeta la URL que se le fije aquí; solo cae a Settings
    cuando nadie la puso.
    """
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """El esquema se aplica una vez, con la migración real.

    No con `create_all`: lo que debe probarse es la migración que va a correr en
    el contenedor, no una versión paralela generada desde los modelos.
    """
    command.upgrade(alembic_config(get_settings().database_url), "head")


@pytest.fixture(autouse=True)
def _clean_tables(_schema: None) -> None:
    """Base vacía antes de cada prueba.

    Se borran las filas en orden inverso de dependencias en vez de recrear el
    esquema: es mucho más rápido y las FK siguen validando el orden.
    """
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db() -> Iterator[SASession]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Cliente HTTP con el ciclo de vida completo, así que corre el bootstrap.

    `base_url` con https porque la cookie de sesión del panel es `https_only`:
    con http el navegador (y el cliente de pruebas) nunca la guardaría y todas
    las pruebas de login fallarían por una razón que no es la real.
    """
    with TestClient(create_app(), base_url="https://mesh.test") as c:
        yield c


@pytest.fixture
def tmp_db_url() -> str:
    """URL de una base vacía y desechable, para pruebas de migración."""
    path = Path(tempfile.mkdtemp(prefix="agent-mesh-migr-")) / "m.db"
    return f"sqlite:///{path}"


@pytest.fixture
def migrated_engine(tmp_db_url: str) -> Iterator[Engine]:
    """Base independiente con el esquema aplicado por la migración."""
    command.upgrade(alembic_config(tmp_db_url), "head")
    fresh = create_engine(tmp_db_url)
    try:
        yield fresh
    finally:
        fresh.dispose()


# --------------------------------------------------------- ayudas de la API v1


@pytest.fixture
def mundo(db: SASession) -> "Mundo":
    """El escenario de SPEC §3: dos proyectos, tres personas, tokens emitidos.

    Es deliberadamente el ejemplo del spec y no un caso mínimo, porque las
    pruebas que más importan son las de aislamiento, y esas necesitan que exista
    un segundo proyecto al que asomarse.
    """
    from app.services import identity

    pablo_proj = identity.create_project(db, slug="proyecto-pablo", name="Pedidos")
    luis_proj = identity.create_project(db, slug="proyecto-luis", name="Portal")

    victor = identity.create_person(db, email="victor@e.test", display_name="victor")
    pablo = identity.create_person(db, email="pablo@e.test", display_name="pablo")
    luis = identity.create_person(db, email="luis@e.test", display_name="luis")

    identity.add_member(db, project=pablo_proj, person=victor)
    identity.add_member(db, project=pablo_proj, person=pablo)
    identity.add_member(db, project=luis_proj, person=victor)
    identity.add_member(db, project=luis_proj, person=luis)

    tokens_por_persona = {
        p.display_name: identity.issue_token(db, person=p).plain for p in (victor, pablo, luis)
    }
    db.commit()
    return Mundo(tokens=tokens_por_persona)


class Mundo:
    """Tokens del escenario, y el atajo para autenticar peticiones."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens

    def auth(self, persona: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[persona]}"}

    def sesion(self, persona: str, session_key: str) -> dict[str, str]:
        return {**self.auth(persona), "X-Mesh-Session": session_key}
