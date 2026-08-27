"""Tipos de columna propios.

`UtcDateTime` existe por un defecto concreto y fácil de pasar por alto: SQLite no
persiste la zona horaria. SQLAlchemy guarda el instante en UTC pero lo devuelve
*naive*, así que un mismo campo salía por la API con `Z` cuando el objeto acababa
de crearse en memoria y **sin** `Z` cuando venía de la base. `references/api.md`
documenta el formato con `Z`, y un agente que compare dos timestamps con formatos
distintos se equivoca en silencio.

Con este tipo, todo lo que sale de la base es consciente de la zona y siempre en
UTC. En Postgres, donde `timestamptz` sí guarda la zona, el comportamiento es el
mismo y el tipo es inocuo.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """`DateTime` que entra y sale siempre en UTC y con `tzinfo`."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            # Un naive aquí sería una fecha de zona desconocida: guardarla como
            # si fuera UTC es exactamente el error que este tipo evita.
            msg = "UtcDateTime exige un datetime con tzinfo"
            raise ValueError(msg)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
