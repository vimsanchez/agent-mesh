"""M4: las dos formas de dirección.

victor.db        buzón del rol
victor.db.a7f3   esa sesión concreta
"""

import pytest

from app.services import addressing
from app.services.errors import ValidationFailedError

# ------------------------------------------------------------------- formateo


def test_sin_sufijo_es_el_buzon_del_rol() -> None:
    assert addressing.format_address("victor", "db") == "victor.db"


def test_con_sufijo_apunta_a_una_sesion() -> None:
    assert addressing.format_address("victor", "db", "a7f3") == "victor.db.a7f3"


def test_el_sufijo_es_estable_para_una_misma_sesion() -> None:
    """Si cambiara entre llamadas, una réplica no encontraría a quien atendió."""
    uno = addressing.session_suffix("sid_abc123")
    otro = addressing.session_suffix("sid_abc123")

    assert uno == otro
    assert len(uno) == addressing.SUFFIX_LENGTH


def test_sesiones_distintas_dan_sufijos_distintos() -> None:
    sufijos = {addressing.session_suffix(f"sid_{i:024x}") for i in range(500)}

    # Con 4 hex hay 65536 posibles: en 500 muestras cabe alguna colisión, pero
    # no un colapso. Lo que se comprueba es que dispersa, no que sea único —
    # la unicidad entre hermanas la garantiza `register`.
    assert len(sufijos) > 480


def test_el_sufijo_no_revela_el_id_de_sesion() -> None:
    """Va en una dirección pública; no debe filtrar el identificador interno."""
    session_id = "sid_0123456789abcdef01234567"

    sufijo = addressing.session_suffix(session_id)

    assert sufijo not in session_id


# --------------------------------------------------------------------- parseo


def test_parsea_el_buzon_del_rol() -> None:
    parsed = addressing.parse_address("pablo.general")

    assert parsed.person == "pablo"
    assert parsed.role == "general"
    assert parsed.suffix is None
    assert parsed.is_role_mailbox


def test_parsea_una_direccion_de_sesion() -> None:
    parsed = addressing.parse_address("victor.db.a7f3")

    assert parsed.person == "victor"
    assert parsed.role == "db"
    assert parsed.suffix == "a7f3"
    assert not parsed.is_role_mailbox


@pytest.mark.parametrize(
    "basura",
    [
        "victor",
        "victor.",
        ".db",
        "victor..db",
        "victor.db.a7f3.extra",
        "",
        ".",
    ],
)
def test_una_direccion_mal_formada_es_rechazada(basura: str) -> None:
    """Aceptarla en silencio dejaría mensajes dirigidos a nadie."""
    with pytest.raises(ValidationFailedError):
        addressing.parse_address(basura)


def test_ida_y_vuelta() -> None:
    for direccion in ("victor.db", "victor.db.a7f3", "pablo.general"):
        parsed = addressing.parse_address(direccion)
        rearmada = addressing.format_address(parsed.person, parsed.role, parsed.suffix)
        assert rearmada == direccion
