"""Presentación de fechas en la zona de quien lee.

Lo que se guarda y lo que responde la API sigue siendo UTC; esto es solo
formato de salida (panel y exportaciones).
"""

from datetime import UTC, datetime

from app.services import timefmt


def test_convierte_utc_a_la_zona_configurada() -> None:
    """Las 22:08 UTC son las 16:08 en Ciudad de México (-6)."""
    momento = datetime(2026, 8, 31, 22, 8, 30, tzinfo=UTC)

    salida = timefmt.stamp(momento, timefmt.zona("America/Mexico_City"))

    assert salida == "2026-08-31 16:08 CST"


def test_la_marca_puede_traer_segundos() -> None:
    momento = datetime(2026, 8, 31, 22, 8, 30, tzinfo=UTC)

    salida = timefmt.stamp(momento, timefmt.zona("America/Mexico_City"), segundos=True)

    assert salida == "2026-08-31 16:08:30 CST"


def test_la_fecha_sola_tambien_se_convierte() -> None:
    """En UTC-6, lo ocurrido de madrugada UTC cae el día anterior aquí."""
    madrugada = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)

    assert timefmt.day(madrugada, timefmt.zona("America/Mexico_City")) == "2026-08-31"


def test_una_zona_invalida_cae_a_utc_sin_tumbar_nada() -> None:
    """Una imagen sin tzdata, o un nombre mal escrito, no puede romper el panel.

    Degradar a UTC muestra una hora correcta aunque no sea la local; fallar
    dejaría al administrador sin panel por un detalle de presentación.
    """
    momento = datetime(2026, 8, 31, 22, 8, 30, tzinfo=UTC)

    salida = timefmt.stamp(momento, timefmt.zona("Marte/Olympus_Mons"))

    assert salida == "2026-08-31 22:08 UTC"


def test_un_naive_se_asume_utc_y_no_revienta() -> None:
    """La base siempre devuelve fechas con tzinfo (db/types.py), pero un naive
    que se cuele por otra vía debe formatearse, no lanzar."""
    salida = timefmt.stamp(
        datetime(2026, 8, 31, 22, 8, 30), timefmt.zona("America/Mexico_City")
    )

    assert salida == "2026-08-31 16:08 CST"
