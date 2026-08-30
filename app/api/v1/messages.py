"""Envío, inbox con long polling, confirmación e hilos.

Sobre los dos relojes (SPEC §5.4), que es fácil confundir:

- El timeout de `GET /inbox` (~30 s) significa "no hay nada nuevo ahora, vuelve a
  preguntar". **No dice nada sobre el otro agente.**
- El tiempo de la conversación son minutos u horas: lo que el otro tarda en leer,
  razonar, trabajar y contestar.

El agente nunca se bloquea esperando una respuesta concreta.
"""

import asyncio

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.api.v1.schemas import (
    AckOut,
    ClaimOut,
    DismissOut,
    InboxOut,
    MessageOut,
    ProgressOut,
    SendIn,
    SentOut,
    ThreadOut,
    ThreadResolvedOut,
    ThreadsOut,
    ThreadSummary,
    UnclaimedOut,
)
from app.config import Settings
from app.db.enums import ThreadStatus
from app.db.models import AgentSession, Message, Thread
from app.db.session import SessionLocal
from app.security.deps import Config, CurrentSession, Db
from app.services import messaging
from app.services.errors import NotFoundError

router = APIRouter(tags=["messages"])

# Cada cuánto se vuelve a mirar durante el long poll. Medio segundo es
# imperceptible frente a los minutos que tarda un agente en contestar, y con 30 s
# de espera son 60 consultas diminutas por conexión.
POLL_INTERVAL_SECONDS = 0.5


def _to_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        thread_id=message.thread_id,
        in_reply_to=message.in_reply_to,
        sender=message.sender_address,
        to=message.recipient_address,
        kind=message.kind,
        subject=message.subject,
        body=message.body,
        status=message.status,
        created_at=message.created_at,
    )


@router.post("/messages", response_model=SentOut, status_code=201)
def send(db: Db, agent_session: CurrentSession, settings: Config, body: SendIn) -> SentOut:
    """Envía un mensaje.

    Un `to` que apunta a un rol que nadie ha levantado no falla: el mensaje
    espera. Y un `kind: answer` con `in_reply_to` cierra el mensaje original.
    La respuesta trae el estado de la conversación (C2 de SPEC-DELTA).
    """
    enviado = messaging.send(
        db,
        sender=agent_session,
        to=body.to,
        kind=body.kind,
        subject=body.subject,
        body=body.body,
        in_reply_to=body.in_reply_to,
        thread_id=body.thread_id,
    )
    feedback = messaging.feedback_for(db, settings, sent=enviado)
    salida = SentOut(
        id=enviado.message.id,
        thread_id=enviado.thread.id,
        status=enviado.message.status,
        thread_status=feedback.thread_status,
        thread_message_count=feedback.thread_message_count,
        hint=feedback.hint,
    )
    db.commit()
    return salida


def _poll_once(session_key: str, settings: Settings) -> list[MessageOut]:
    """Una pasada del inbox, con su propia sesión de base de datos.

    Abre y cierra en cada pasada a propósito: mantener una transacción abierta
    los 30 s que dura el long poll retendría un snapshot de SQLite durante toda
    la conexión, y habría varias conexiones así a la vez.

    Se relee la sesión por su clave en cada pasada en lugar de arrastrar el
    objeto: así, si la sesión caduca a mitad del poll, la siguiente pasada lo ve.
    """
    with SessionLocal() as db:
        agent_session = db.scalar(
            select(AgentSession).where(AgentSession.session_key == session_key)
        )
        if agent_session is None or agent_session.status != "active":
            return []

        messaging.refresh(db, settings, project_id=agent_session.project_id)
        mailbox, precise = messaging.addresses_of(db, agent_session)
        mensajes = messaging.collect_inbox(
            db, agent_session=agent_session, mailbox=mailbox, precise=precise
        )
        salida = [_to_out(m) for m in mensajes]
        db.commit()
        return salida


@router.get("/inbox", response_model=InboxOut)
async def inbox(
    agent_session: CurrentSession,
    settings: Config,
    wait: int = Query(default=0, ge=0, description="Segundos de espera máxima."),
) -> InboxOut:
    """Long poll. Devuelve en cuanto haya algo, o vacío al vencer la espera.

    El handler es `async` pero las consultas son síncronas, así que van a un hilo
    aparte: si se ejecutaran aquí, una sola conexión en espera bloquearía el
    event loop y con ella a todos los demás agentes.
    """
    session_key = agent_session.session_key
    espera = min(wait, settings.longpoll_max_seconds)

    mensajes = await run_in_threadpool(_poll_once, session_key, settings)
    if mensajes or espera <= 0:
        return InboxOut(messages=mensajes)

    limite = asyncio.get_running_loop().time() + espera
    while asyncio.get_running_loop().time() < limite:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        mensajes = await run_in_threadpool(_poll_once, session_key, settings)
        if mensajes:
            break
    return InboxOut(messages=mensajes)


@router.post("/messages/{message_id}/ack", response_model=AckOut)
def ack(db: Db, agent_session: CurrentSession, message_id: str) -> AckOut:
    """Confirma recepción. Sin esto, si la sesión muere el mensaje reaparece.

    Devuelve la llave del hilo (C1 de SPEC-DELTA): el agente que no apuntó nada
    conserva `thread_id` y asunto en la misma salida que acaba de leer.
    """
    message = messaging.ack(db, agent_session=agent_session, message_id=message_id)
    hilo = db.get(Thread, message.thread_id)
    if hilo is None:  # pragma: no cover - lo impide la FK
        raise NotFoundError(f"no existe el hilo '{message.thread_id}' en este proyecto")
    salida = AckOut(
        id=message.id,
        status=message.status,
        acked=True,
        thread_id=hilo.id,
        thread_status=hilo.status,
        subject=message.subject,
    )
    db.commit()
    return salida


@router.post("/messages/{message_id}/progress", response_model=ProgressOut)
def progress(db: Db, agent_session: CurrentSession, message_id: str) -> ProgressOut:
    """Marca `in_progress`: el remitente ve "lo están atendiendo"."""
    message = messaging.progress(db, agent_session=agent_session, message_id=message_id)
    salida = ProgressOut(id=message.id, status=message.status)
    db.commit()
    return salida


@router.get("/unclaimed", response_model=UnclaimedOut)
def unclaimed(db: Db, agent_session: CurrentSession, settings: Config) -> UnclaimedOut:
    """Mensajes que nadie está atendiendo, menos los que esta sesión descartó.

    Se pone al día el proyecto antes de mirar: si no, seguirían fuera de la
    bandeja los mensajes de sesiones que ya murieron sin confirmar.
    """
    messaging.refresh(db, settings, project_id=agent_session.project_id)
    mensajes = messaging.unclaimed_for(db, agent_session=agent_session)
    salida = UnclaimedOut(messages=[_to_out(m) for m in mensajes])
    db.commit()
    return salida


@router.post("/messages/{message_id}/claim", response_model=ClaimOut)
def claim(db: Db, agent_session: CurrentSession, message_id: str) -> ClaimOut:
    """Reclamo atómico. `409` si otra sesión se adelantó.

    Ese 409 no es un fallo: significa que ya lo atiende alguien. Al reclamar algo
    dirigido a otro rol, el servicio avisa al remitente por su cuenta.
    """
    message = messaging.claim(db, agent_session=agent_session, message_id=message_id)
    salida = ClaimOut(id=message.id, status=message.status, claimed=True)
    db.commit()
    return salida


@router.post("/messages/{message_id}/dismiss", response_model=DismissOut)
def dismiss(db: Db, agent_session: CurrentSession, message_id: str) -> DismissOut:
    """Descarte por sesión: otras sesiones lo siguen viendo."""
    message = messaging.dismiss(db, agent_session=agent_session, message_id=message_id)
    salida = DismissOut(id=message.id, dismissed=True)
    db.commit()
    return salida


@router.get("/threads", response_model=ThreadsOut)
def threads(
    db: Db,
    agent_session: CurrentSession,
    status: ThreadStatus | None = None,
) -> ThreadsOut:
    """Hilos del proyecto de la sesión, con conteo de mensajes (C3)."""
    filas = messaging.threads_overview(
        db, project_id=agent_session.project_id, status=status
    )
    return ThreadsOut(
        threads=[
            ThreadSummary(
                id=hilo.id,
                subject=hilo.subject,
                status=hilo.status,
                message_count=total,
                updated_at=hilo.updated_at,
            )
            for hilo, total in filas
        ]
    )


@router.post("/threads/{thread_id}/resolve", response_model=ThreadResolvedOut)
def resolve(db: Db, agent_session: CurrentSession, thread_id: str) -> ThreadResolvedOut:
    """Cierra un hilo. Idempotente; un send posterior lo reabre solo (C3)."""
    hilo = messaging.resolve_thread(db, agent_session=agent_session, thread_id=thread_id)
    salida = ThreadResolvedOut(id=hilo.id, subject=hilo.subject, status=hilo.status)
    db.commit()
    return salida


@router.get("/threads/{thread_id}", response_model=ThreadOut)
def thread(db: Db, agent_session: CurrentSession, thread_id: str) -> ThreadOut:
    """Hilo completo en orden cronológico."""
    hilo, mensajes = messaging.thread_with_messages(
        db, agent_session=agent_session, thread_id=thread_id
    )
    return ThreadOut(
        id=hilo.id,
        subject=hilo.subject,
        status=hilo.status,
        messages=[_to_out(m) for m in mensajes],
    )
