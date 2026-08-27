"""Traducción de errores de dominio a HTTP. **El único lugar donde ocurre.**

Los servicios lanzan excepciones de dominio y no saben que existe HTTP; los
handlers no atrapan nada. Todo el mapeo vive aquí, así que la tabla de códigos de
`references/api.md` se puede leer de un solo vistazo.

El cuerpo es siempre `{"detail": "..."}`, y ese texto está escrito para que lo lea
un agente: dice qué hacer, no solo qué pasó (regla 10).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    SessionGoneError,
    UnauthorizedError,
    ValidationFailedError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    UnauthorizedError: 401,
    ForbiddenError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    SessionGoneError: 410,
    ValidationFailedError: 422,
}


def register_error_handlers(app: FastAPI) -> None:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, DomainError)
        # 500 por defecto: un error de dominio sin mapeo es un olvido nuestro,
        # no algo que el agente pueda arreglar. Mejor que se note.
        status = STATUS_BY_ERROR.get(type(exc), 500)
        return JSONResponse(status_code=status, content={"detail": exc.detail})

    for error_type in STATUS_BY_ERROR:
        app.add_exception_handler(error_type, handle)
    app.add_exception_handler(DomainError, handle)
