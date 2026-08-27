"""Hashing de contraseñas de administrador con Argon2id.

Regla 7 de CLAUDE.md: jamás texto plano, jamás en logs, jamás en respuestas de la
API. Este módulo es el único lugar del sistema que toca una contraseña.

Argon2id es lo correcto **aquí** porque una contraseña es de baja entropía y hay
que encarecer el intento por fuerza bruta. Para los tokens de agente la decisión
es distinta y está explicada en `app/security/tokens.py`.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Los parámetros por defecto de argon2-cffi ya son Argon2id con valores
# recomendados por la propia librería. No se bajan.
_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """`False` en vez de excepción: quien llama solo necesita saber si entra.

    Se capturan también los hashes corruptos o de otro algoritmo, para que una
    fila mal escrita en la base no tumbe el login con un 500.
    """
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """`True` si el hash se hizo con parámetros más flojos que los actuales."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True
