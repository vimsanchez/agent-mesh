"""Registro y ciclo de vida de una sesión de agente."""

from fastapi import APIRouter

from app.api.v1.schemas import ClosedOut, HeartbeatOut, RegisterIn, SessionOut
from app.security.deps import Config, CurrentPerson, Db
from app.services import messaging, sessions

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionOut, status_code=201)
def register(db: Db, person: CurrentPerson, body: RegisterIn) -> SessionOut:
    """Registra una sesión en un proyecto donde la persona ya es miembro.

    `403` si no lo es y `404` si el slug no existe; en ambos casos el `detail`
    dice qué hacer, para que el agente se detenga en vez de improvisar.
    """
    agent_session = sessions.register(
        db, person=person, slug=body.project, role_label=body.role
    )
    address = sessions.address_of(db, agent_session)
    session_address = sessions.address_of(db, agent_session, precise=True)
    db.commit()
    return SessionOut(
        session_key=agent_session.session_key,
        address=address,
        session_address=session_address,
        project=body.project.strip().lower(),
        registered_at=agent_session.registered_at,
    )


@router.post("/sessions/{session_key}/heartbeat", response_model=HeartbeatOut)
def heartbeat(
    db: Db, person: CurrentPerson, settings: Config, session_key: str
) -> HeartbeatOut:
    agent_session = sessions.heartbeat(
        db, person=person, session_key=session_key, settings=settings
    )
    address = sessions.address_of(db, agent_session)
    db.commit()
    return HeartbeatOut(
        address=address,
        status=agent_session.status,
        last_seen_at=agent_session.last_seen_at,
    )


@router.delete("/sessions/{session_key}", response_model=ClosedOut)
def close(db: Db, person: CurrentPerson, session_key: str) -> ClosedOut:
    """Cierre limpio: los mensajes entregados sin `ack` vuelven a circular."""
    agent_session = messaging.close_session(db, person=person, session_key=session_key)
    address = sessions.address_of(db, agent_session)
    db.commit()
    return ClosedOut(address=address, status=agent_session.status)
