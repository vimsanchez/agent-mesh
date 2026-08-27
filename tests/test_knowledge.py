"""M7: las cuatro intenciones, como función pura.

`apply_intent` no toca la base, así que las reglas de reescritura se prueban sin
montar un proyecto. Es también la garantía de que lo que se guarda como versión
es exactamente lo que esta función devolvió.
"""

import pytest

from app.services.errors import ValidationFailedError
from app.services.knowledge import OBSOLETE_HEADING, apply_intent

DOC = """# API de pedidos

Contrato entre backend y cliente.

## Paginación

Por offset.

## Autenticación

Bearer.
"""


def _aplicar(intent: str, aporte: str, anchor: str | None = None) -> str:
    return apply_intent(
        content=DOC,
        intent=intent,
        anchor=anchor,
        aporte=aporte,
        author_address="victor.db",
        rationale="acordado en thr_8f2a",
    )


# --------------------------------------------------------------------- create


def test_create_reemplaza_todo() -> None:
    resultado = apply_intent(
        content="",
        intent="create",
        anchor=None,
        aporte="# Nuevo\n\nContenido.",
        author_address="victor.db",
        rationale="x",
    )

    assert resultado == "# Nuevo\n\nContenido.\n"


# --------------------------------------------------------------------- append


def test_append_agrega_al_final_sin_tocar_lo_anterior() -> None:
    resultado = _aplicar("append", "## Ordenamiento\n\nPor fecha.")

    assert resultado.startswith("# API de pedidos")
    assert "## Paginación" in resultado
    assert resultado.rstrip().endswith("Por fecha.")


def test_append_sobre_documento_vacio() -> None:
    resultado = apply_intent(
        content="",
        intent="append",
        anchor=None,
        aporte="## Primera",
        author_address="victor.db",
        rationale="x",
    )

    assert resultado == "## Primera\n"


def test_append_ignora_el_ancla() -> None:
    """Añadir es al final. Para añadir dentro de una sección, eso es `amend`."""
    con_ancla = _aplicar("append", "## Extra\n\nX.", anchor="## Paginación")
    sin_ancla = _aplicar("append", "## Extra\n\nX.")

    assert con_ancla == sin_ancla


# ---------------------------------------------------------------------- amend


def test_amend_reemplaza_solo_la_seccion_del_ancla() -> None:
    resultado = _aplicar("amend", "Por cursor opaco.", anchor="## Paginación")

    assert "Por cursor opaco." in resultado
    assert "Por offset." not in resultado
    assert "Bearer." in resultado, "las otras secciones no se tocan"
    assert "# API de pedidos" in resultado, "el preámbulo se conserva"


def test_amend_conserva_el_orden_de_las_secciones() -> None:
    resultado = _aplicar("amend", "Por cursor.", anchor="## Paginación")

    assert resultado.index("## Paginación") < resultado.index("## Autenticación")


def test_amend_sin_ancla_falla() -> None:
    with pytest.raises(ValidationFailedError, match="anchor"):
        _aplicar("amend", "X.")


def test_un_ancla_inexistente_dice_cuales_hay() -> None:
    """Un agente con un error vago improvisa; uno con la lista, corrige."""
    with pytest.raises(ValidationFailedError) as error:
        _aplicar("amend", "X.", anchor="## No existe")

    assert "## Paginación" in str(error.value)
    assert "## Autenticación" in str(error.value)


# ------------------------------------------------------------------ deprecate


def test_deprecate_no_borra_mueve_al_final() -> None:
    """Regla explícita del §6.3: no borra, marca como obsoleto."""
    resultado = _aplicar("deprecate", "", anchor="## Paginación")

    assert OBSOLETE_HEADING in resultado
    assert "Por offset." in resultado, "el contenido original se conserva"
    assert resultado.index(OBSOLETE_HEADING) > resultado.index("## Autenticación")


def test_deprecate_deja_constancia_de_quien_y_por_que() -> None:
    resultado = _aplicar("deprecate", "", anchor="## Paginación")

    assert "victor.db" in resultado
    assert "acordado en thr_8f2a" in resultado


def test_deprecate_dos_veces_reusa_la_seccion_obsoleto() -> None:
    """Si creara una segunda `## Obsoleto`, el documento tendría dos."""
    una = _aplicar("deprecate", "", anchor="## Paginación")
    dos = apply_intent(
        content=una,
        intent="deprecate",
        anchor="## Autenticación",
        aporte="",
        author_address="pablo.general",
        rationale="ya no aplica",
    )

    assert dos.count(OBSOLETE_HEADING) == 1
    assert "Por offset." in dos
    assert "Bearer." in dos


def test_deprecate_sin_ancla_falla() -> None:
    with pytest.raises(ValidationFailedError, match="anchor"):
        _aplicar("deprecate", "")


def test_un_intent_desconocido_falla() -> None:
    with pytest.raises(ValidationFailedError):
        _aplicar("borrar-todo", "X.", anchor="## Paginación")
