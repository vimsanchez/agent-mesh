"""M4: `UtcDateTime`.

Existe porque SQLite no persiste la zona y la API emitía dos formatos distintos
para el mismo campo según si el dato venía de memoria o de la base.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.services import identity


def test_lo_leido_de_la_base_trae_zona(db: Session) -> None:
    """El defecto original: esto venía naive y se serializaba sin `Z`."""
    person = identity.create_person(db, email="v@e.test", display_name="victor")
    db.commit()
    db.expire_all()

    recargada = identity.get_person(db, person.id)

    assert recargada.created_at.tzinfo is not None
    assert recargada.created_at.utcoffset() == timedelta(0)


def test_un_instante_en_otra_zona_se_guarda_en_utc(db: Session) -> None:
    """Guardar la hora local y perder el offset falsearía el instante."""
    en_cdmx = datetime(2026, 8, 27, 0, 0, 0, tzinfo=timezone(timedelta(hours=-6)))
    person = identity.create_person(db, email="v@e.test", display_name="victor")
    person.created_at = en_cdmx
    db.commit()
    db.expire_all()

    recargada = identity.get_person(db, person.id)

    assert recargada.created_at == en_cdmx
    assert recargada.created_at.hour == 6, "00:00 en UTC-6 son las 06:00 UTC"


def test_un_datetime_naive_es_rechazado(db: Session) -> None:
    """Una fecha sin zona es de zona desconocida; asumir UTC es el bug a evitar."""
    person = identity.create_person(db, email="v@e.test", display_name="victor")
    person.created_at = datetime(2026, 8, 27, 0, 0, 0)

    # SQLAlchemy envuelve el ValueError del tipo en StatementError.
    with pytest.raises(StatementError, match="tzinfo") as capturado:
        db.flush()
    assert isinstance(capturado.value.orig, ValueError)


def test_utcnow_es_consciente_de_la_zona() -> None:
    ahora = utcnow()

    assert ahora.tzinfo is UTC
