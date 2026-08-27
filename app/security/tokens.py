"""Tokens personales de agente.

**Por qué SHA-256 y no Argon2id, si la regla 7 dice Argon2id.**

La regla 7 habla de *contraseñas*, y una contraseña se protege con un hash lento
porque tiene poca entropía: hay que encarecer cada intento de adivinarla. Un
token aquí no se adivina: son 256 bits de `secrets.token_urlsafe`, así que no
existe diccionario ni fuerza bruta viable que atacar. Estirar el hash no compra
seguridad.

Y sí cuesta: el token se verifica en **cada petición**, incluido cada `GET /inbox`
con long polling. Argon2 está calibrado a propósito para tardar cientos de
milisegundos; ponerlo en ese camino haría el servicio inservible.

Con un hash rápido el lookup además es directo: se hashea lo que llegó y se busca
por índice único. No hace falta ninguna columna de prefijo — eso solo se necesita
cuando el hash es salado y no se puede indexar, que no es el caso.

Lo que sí se mantiene de la regla 7: **en la base solo vive el hash**. El valor en
claro se muestra una vez al emitirlo y no hay forma de recuperarlo.
"""

import hashlib
import secrets
from typing import Final

# Prefijo visible para que un token filtrado en un log o un pegado accidental se
# reconozca de inmediato como credencial de Agent Mesh.
TOKEN_PREFIX: Final = "amt_"
_ENTROPY_BYTES: Final = 32


def new_token() -> str:
    """Token en claro. Se muestra una sola vez y no se guarda así en ningún lado."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(_ENTROPY_BYTES)}"


def hash_token(plain: str) -> str:
    """SHA-256 en hex. Determinista, por eso se puede buscar por índice."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def looks_like_token(value: str) -> bool:
    """Filtro baratísimo antes de tocar la base.

    No es una comprobación de seguridad: solo evita una consulta por cada
    cabecera `Authorization` mal formada.
    """
    return value.startswith(TOKEN_PREFIX) and len(value) > len(TOKEN_PREFIX) + 20
