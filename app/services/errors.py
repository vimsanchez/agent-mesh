"""Errores de dominio.

Se traducen a HTTP en un solo lugar (`app/api/errors.py`), nunca en los
servicios: la lógica de dominio no sabe que existe HTTP.

`detail` es lo que va a leer un agente. Regla 10 de CLAUDE.md: un agente con un
error vago improvisa; uno con instrucción se detiene. Así que cada mensaje dice
qué hacer, no solo qué pasó.
"""


class DomainError(Exception):
    """Raíz de todos los errores de dominio."""

    detail = "error de dominio"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class NotFoundError(DomainError):
    detail = "no existe"


class ConflictError(DomainError):
    """Choque con el estado actual: nombre tomado, versión desfasada, etc."""

    detail = "conflicto con el estado actual"


class ForbiddenError(DomainError):
    """La credencial es válida pero no alcanza para esto."""

    detail = "no autorizado"


class UnauthorizedError(DomainError):
    detail = "credencial inválida o revocada"


class ValidationFailedError(DomainError):
    detail = "datos inválidos"
