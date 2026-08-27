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
from fastapi.testclient import TestClient  # noqa: E402

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
