"""M1: el cableado de Alembic funciona en una base limpia.

Todavía no hay revisiones (eso es M2), pero si `env.py` está mal configurado
esto falla ahora y no dentro de tres pasos.
"""

from alembic import command
from alembic.config import Config


def _alembic_config(db_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_upgrade_y_downgrade_en_base_limpia(tmp_db_url: str) -> None:
    config = _alembic_config(tmp_db_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
