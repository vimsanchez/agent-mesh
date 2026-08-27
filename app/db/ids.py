"""Identificadores públicos con prefijo.

La API los expone tal cual (`msg_1c9e…`, `thr_8f2a…`, `ses_9a1f…`, `doc_…`), así
que el prefijo forma parte del contrato, no es decoración: un agente que lee un
id sabe de inmediato a qué apunta y no confunde un hilo con un mensaje.

Son opacos y no adivinables. No se derivan de contadores, para que nadie pueda
enumerar los mensajes de un proyecto ajeno probando ids consecutivos.
"""

import secrets
from typing import Final

ADMIN: Final = "adm"
PERSON: Final = "per"
TOKEN: Final = "tok"
PROJECT: Final = "prj"
SESSION: Final = "sid"
SESSION_KEY: Final = "ses"
THREAD: Final = "thr"
MESSAGE: Final = "msg"
DOCUMENT: Final = "doc"
VERSION: Final = "ver"

_ENTROPY_BYTES: Final = 12


def new_id(prefix: str) -> str:
    """`prefix_<24 hex>`. 96 bits de entropía."""
    return f"{prefix}_{secrets.token_hex(_ENTROPY_BYTES)}"


def new_session_key() -> str:
    """Clave de sesión para la cabecera `X-Mesh-Session`.

    Más entropía que un id normal: viaja en cada petición y, aunque el token de
    la persona es la credencial real, esto no debe ser adivinable.
    """
    return f"{SESSION_KEY}_{secrets.token_urlsafe(32)}"
