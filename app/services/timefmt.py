"""Fechas en la zona horaria de quien lee.

Esto es **solo presentación**. Lo que se guarda en la base y lo que responde la
API sigue siendo UTC, y debe seguir siéndolo por dos razones concretas:

- `services/sessions.expire_stale_sessions` compara `last_seen_at` contra
  `utcnow()`. Guardar horas locales haría que la caducidad se equivocara por el
  tamaño del huso, y con ella la recirculación de mensajes.
- `references/api.md` documenta los timestamps con `Z`, y el mesh conecta
  máquinas de personas que no tienen por qué estar en el mismo huso: UTC es la
  referencia común.

El panel y las exportaciones se generan al vuelo desde la base, así que cambiar
esta capa arregla también todo lo que ya existe.
"""

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zona(nombre: str) -> tzinfo:
    """La zona configurada, o UTC si el nombre no existe en esta máquina.

    Una imagen sin `tzdata` o un nombre mal escrito no pueden tumbar el panel:
    degradar a UTC muestra una hora correcta aunque no sea la local.
    """
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def local(momento: datetime, tz: tzinfo) -> datetime:
    """El mismo instante, visto desde `tz`.

    Un naive se asume UTC: es lo que guarda SQLite cuando algo esquiva
    `UtcDateTime`, y formatear mal es preferible a lanzar en una plantilla.
    """
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento.astimezone(tz)


def day(momento: datetime, tz: tzinfo) -> str:
    """Solo la fecha, ya convertida.

    Convertir importa aunque no se muestre la hora: en UTC-6, todo lo ocurrido
    entre las 00:00 y las 06:00 UTC cae el día anterior en el calendario de
    quien lee.
    """
    return local(momento, tz).strftime("%Y-%m-%d")


def stamp(momento: datetime, tz: tzinfo, *, segundos: bool = False) -> str:
    """`2026-08-31 16:08 CST`. Con la abreviatura, porque una hora sin zona en
    un sistema que cruza máquinas es una hora ambigua."""
    patron = "%Y-%m-%d %H:%M:%S %Z" if segundos else "%Y-%m-%d %H:%M %Z"
    return local(momento, tz).strftime(patron)
