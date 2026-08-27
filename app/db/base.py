"""Base declarativa y convención de nombres de constraints.

La convención explícita es lo que permite que Alembic genere migraciones con
nombres estables en SQLite y en Postgres. Sin ella, SQLite deja constraints
anónimos y un `ALTER` posterior no los encuentra.
"""

from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Ahora, en UTC y con tzinfo.

    El default se calcula en Python y no con `func.now()` del motor: así SQLite y
    Postgres guardan exactamente lo mismo y migrar no cambia los timestamps.

    Ojo al leer: SQLite no persiste la zona, así que devuelve datetimes naive
    aunque la columna sea `DateTime(timezone=True)`. Quien compare fechas debe
    normalizar, no asumir tzinfo.
    """
    return datetime.now(UTC)
