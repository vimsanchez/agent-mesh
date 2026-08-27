"""Direcciones públicas de agente. Dos formas, jerárquicas.

    victor.db          el BUZÓN DEL ROL: cualquier sesión viva con ese rol
    victor.db.a7f3     esa SESIÓN CONCRETA

El buzón del rol es la forma principal y la razón del diseño (SPEC §3): permite
escribirle "al de base de datos" sin saber qué sesión concreta está viva. Nunca
caduca y es la que se cita en los acuerdos.

El sufijo es **opcional** y añade precisión encima. Sirve para dos cosas:

- Que el roster sea legible cuando la misma persona tiene dos sesiones con el
  mismo rol, que es un caso real (dos terminales en worktrees distintos, o una
  sesión huérfana que todavía no caduca).
- Que una réplica vuelva a la sesión que efectivamente atendió el hilo, en vez de
  caer otra vez al reclamo y que se la lleve otra.

El sufijo se **deriva** de `sessions.id`, no se guarda: no hay columna nueva ni
migración. Cambia en cada `register`, así que no sirve para apuntarlo a largo
plazo — para eso está el buzón del rol.

Por eso ni `display_name` ni `role_label` admiten puntos: el punto es lo que
separa los tres niveles, y uno de más volvería la dirección ambigua.
"""

import hashlib
from dataclasses import dataclass
from typing import Final

from app.services.errors import ValidationFailedError

SEPARATOR: Final = "."
SUFFIX_LENGTH: Final = 4


@dataclass(frozen=True)
class ParsedAddress:
    """`suffix is None` significa "el buzón del rol", no "cualquier sufijo"."""

    person: str
    role: str
    suffix: str | None = None

    @property
    def is_role_mailbox(self) -> bool:
        return self.suffix is None


def session_suffix(session_id: str) -> str:
    """Sufijo estable de una sesión, derivado de su id.

    Se hashea en vez de recortar el id directamente para no exponer parte de un
    identificador interno en una dirección pública.
    """
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:SUFFIX_LENGTH]


def format_address(person_name: str, role_label: str, suffix: str | None = None) -> str:
    base = f"{person_name}{SEPARATOR}{role_label}"
    return base if suffix is None else f"{base}{SEPARATOR}{suffix}"


def parse_address(address: str) -> ParsedAddress:
    """`victor.db` o `victor.db.a7f3`. Cualquier otra cosa es error.

    Se valida el número de segmentos en vez de partir por el primer punto: como
    ni el nombre ni el rol admiten puntos, un tercer punto solo puede ser basura,
    y aceptarla en silencio dejaría mensajes dirigidos a nadie.
    """
    partes = address.strip().split(SEPARATOR)
    if len(partes) not in (2, 3) or not all(partes):
        raise ValidationFailedError(
            f"'{address}' no es una dirección válida; usa 'persona.rol' "
            f"(por ejemplo 'pablo.general') o 'persona.rol.sufijo' para una "
            f"sesión concreta"
        )
    person, role, *resto = partes
    return ParsedAddress(person=person, role=role, suffix=resto[0] if resto else None)
