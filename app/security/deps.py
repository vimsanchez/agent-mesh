"""Dependencias de autenticación de la API de agentes.

Dos capas, y conviene no confundirlas:

- El **token** (`Authorization: Bearer`) identifica a la **persona**. Es la
  credencial.
- La **cabecera de sesión** (`X-Mesh-Session`) identifica a la **sesión**. No es
  una credencial: el proyecto y el rol se fijaron al registrar, y sin token no
  sirve para nada.

Varios agentes de la misma persona comparten el token y tienen sesiones distintas
(SPEC §3.2). Eso es correcto y deseado.
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AgentSession, Person
from app.db.session import get_db
from app.services import identity, sessions
from app.services.errors import SessionGoneError, UnauthorizedError

SESSION_HEADER = "X-Mesh-Session"


def current_person(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Person:
    """La persona dueña del token. Se resuelve en cada petición.

    Un token revocado deja de servir de inmediato porque aquí no hay caché.
    """
    if not authorization:
        raise UnauthorizedError(
            "falta la cabecera Authorization; MESH_TOKEN debe estar en el entorno"
        )
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise UnauthorizedError("la cabecera Authorization debe ser 'Bearer <token>'")
    return identity.resolve_token(db, value.strip())


def current_session(
    db: Annotated[Session, Depends(get_db)],
    person: Annotated[Person, Depends(current_person)],
    x_mesh_session: Annotated[str | None, Header()] = None,
) -> AgentSession:
    """La sesión de la cabecera, exigiendo que sea de esta persona.

    Una sesión `stale` o cerrada da 410 y no 404: la respuesta correcta del
    agente es volver a registrarse, no concluir que no existe.
    """
    if not x_mesh_session:
        raise UnauthorizedError(
            f"falta la cabecera {SESSION_HEADER}; regístrate primero con register"
        )
    agent_session = sessions.by_key(db, person=person, session_key=x_mesh_session)
    if agent_session.status != "active":
        raise SessionGoneError
    # Latido implícito: llegar hasta aquí con una sesión válida es señal de vida.
    # Se confirma en su propia transacción para que no dependa de si el handler
    # hace commit (el inbox, por ejemplo, trabaja con otra sesión de BD).
    sessions.touch(db, agent_session)
    db.commit()
    return agent_session


CurrentPerson = Annotated[Person, Depends(current_person)]
CurrentSession = Annotated[AgentSession, Depends(current_session)]
Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]
