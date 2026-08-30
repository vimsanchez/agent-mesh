"""Mensajería: envío, entrega, confirmación e hilos.

Estados de un mensaje, y qué significa cada uno de verdad
---------------------------------------------------------
`pending` es el estado de reposo de un mensaje **con** destinatario, tanto si ese
rol está vivo como si nadie lo ha levantado todavía. Escribirle a `pablo.db`
antes de que Pablo arranque esa sesión no es error: el mensaje espera (SPEC §5.2).

`unclaimed` como *estado* se reserva para los mensajes que **nacen sin
destinatario** (`to: null`, §5.1) y para los que caen ahí al morir su sesión sin
tener a quién volver.

La *bandeja* de no reclamados es más amplia que el estado: incluye también los
`pending` cuyo destinatario no tiene ninguna sesión viva (§5.3). Se calcula al
consultar, no se materializa. Esa distinción es la que permite que un mensaje
dirigido a `pablo.db` esté a la vez esperando a Pablo y visible para quien pueda
resolverlo, sin tener que cambiar de estado y volver atrás cuando Pablo aparezca.

`ack` no aparece en el estado: es un hecho de la entrega y vive en
`message_deliveries.acked_at`, porque una misma dirección puede tener dos
sesiones y cada una tiene su propio ack.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, Select, and_, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import utcnow
from app.db.models import (
    AgentSession,
    Document,
    DocumentVersion,
    Message,
    MessageDelivery,
    MessageDismissal,
    Person,
    Thread,
)
from app.services import addressing, sessions
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError

# Estados en los que un mensaje sigue "en circulación".
OPEN_STATUSES = ("pending", "unclaimed", "delivered", "in_progress")

# Remitente de los mensajes que emite el propio servicio. No es una dirección de
# agente: nadie puede registrarse como "mesh" porque el punto está prohibido en
# los nombres de persona, así que no colisiona con `persona.rol`.
SERVICE_ADDRESS = "mesh"


# ------------------------------------------------------------------ direcciones


def addresses_of(db: Session, agent_session: AgentSession) -> tuple[str, str]:
    """Las dos direcciones que le corresponden a una sesión: buzón y precisa."""
    person = db.get(Person, agent_session.person_id)
    if person is None:  # pragma: no cover - lo impide la FK
        raise NotFoundError("la persona de esta sesión ya no existe")
    mailbox = addressing.format_address(person.display_name, agent_session.role_label)
    precise = addressing.format_address(
        person.display_name,
        agent_session.role_label,
        addressing.session_suffix(agent_session.id),
    )
    return mailbox, precise


def live_recipients(db: Session, *, project_id: str, address: str) -> list[AgentSession]:
    """Sesiones vivas a las que apunta una dirección.

    Con el buzón del rol pueden ser varias; con una dirección precisa, una o
    ninguna. Vacío significa "nadie puede recibirlo ahora", no "la dirección está
    mal": un rol que nadie ha levantado es perfectamente legítimo.
    """
    parsed = addressing.parse_address(address)
    person = db.scalar(select(Person).where(Person.display_name == parsed.person))
    if person is None:
        return []

    candidatas = list(
        db.scalars(
            select(AgentSession).where(
                AgentSession.project_id == project_id,
                AgentSession.person_id == person.id,
                AgentSession.role_label == parsed.role,
                AgentSession.status.in_(sessions.LIVE_STATUSES),
            )
        )
    )
    if parsed.suffix is None:
        return candidatas
    return [s for s in candidatas if addressing.session_suffix(s.id) == parsed.suffix]


# ------------------------------------------------------------------------ envío


@dataclass(frozen=True)
class Sent:
    message: Message
    thread: Thread


def _resolve_thread(
    db: Session,
    *,
    project_id: str,
    subject: str,
    thread_id: str | None,
    in_reply_to: Message | None,
) -> Thread:
    """`thread_id` explícito -> heredado de `in_reply_to` -> hilo nuevo (api.md).

    Un send a un hilo `resolved` lo reabre en la misma transacción (C3): así
    resolver nunca estorba y no hace falta endpoint de reopen ni permiso de
    nadie.
    """
    thread: Thread | None = None
    if thread_id is not None:
        thread = db.get(Thread, thread_id)
        if thread is None or thread.project_id != project_id:
            # Mismo mensaje exista o no en otro proyecto: confirmar que un hilo
            # ajeno existe ya sería filtrar (regla 2).
            raise NotFoundError(f"no existe el hilo '{thread_id}' en este proyecto")
    elif in_reply_to is not None:
        thread = db.get(Thread, in_reply_to.thread_id)
    if thread is not None:
        if thread.status == "resolved":
            thread.status = "open"
        return thread
    thread = Thread(project_id=project_id, subject=subject)
    db.add(thread)
    db.flush()
    return thread


def _resolve_reply_target(
    db: Session, *, project_id: str, in_reply_to: str | None
) -> Message | None:
    if in_reply_to is None:
        return None
    original = db.get(Message, in_reply_to)
    if original is None or original.project_id != project_id:
        raise NotFoundError(f"no existe el mensaje '{in_reply_to}' en este proyecto")
    return original


def send(
    db: Session,
    *,
    sender: AgentSession,
    to: str | None,
    kind: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
    document_path: str | None = None,
    require_document: bool = False,
) -> Sent:
    """Crea un mensaje.

    Un `to` que apunta a un rol inexistente **no es error**: el mensaje espera.
    Lo que sí se valida es la *forma* de la dirección, porque `victor..db` no es
    una dirección que nadie vaya a levantar nunca, es basura.

    Con `require_document` (C5, la compuerta REQUIRE_AGREEMENT_DOC), un
    `agreement` debe citar un documento existente del proyecto: es el mismo
    patrón que el 409 del reclamo — el servicio impone lo que la prosa no logró.
    """
    if not subject.strip():
        raise ValidationFailedError("el asunto no puede estar vacío")
    if to is not None:
        addressing.parse_address(to)
    if (
        kind == "agreement"
        and require_document
        and (
            document_path is None
            or not _document_exists(db, project_id=sender.project_id, path=document_path)
        )
    ):
        raise ValidationFailedError(
            "un agreement debe citar el documento donde quedó escrito; "
            "apórtalo primero con contribute y reintenta con --document-path"
        )

    original = _resolve_reply_target(db, project_id=sender.project_id, in_reply_to=in_reply_to)
    thread = _resolve_thread(
        db,
        project_id=sender.project_id,
        subject=subject,
        thread_id=thread_id,
        in_reply_to=original,
    )

    mailbox, _ = addresses_of(db, sender)
    message = Message(
        project_id=sender.project_id,
        thread_id=thread.id,
        in_reply_to=original.id if original is not None else None,
        sender_session_id=sender.id,
        sender_address=mailbox,
        recipient_address=to,
        kind=kind,
        subject=subject.strip(),
        body=body,
        # Sin destinatario nace en la bandeja de no reclamados (§5.1). Con
        # destinatario espera en `pending`, aunque ese rol no exista todavía.
        status="unclaimed" if to is None else "pending",
    )
    db.add(message)

    if kind == "answer" and original is not None:
        _mark_answered(original)

    thread.updated_at = utcnow()
    db.flush()
    return Sent(message=message, thread=thread)


def _document_exists(db: Session, *, project_id: str, path: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    Document.project_id == project_id, Document.path == path.strip()
                )
            )
        )
    )


@dataclass(frozen=True)
class SendFeedback:
    """Lo que el send devuelve sobre la conversación (C2 de SPEC-DELTA)."""

    thread_status: str
    thread_message_count: int
    hint: str | None


def feedback_for(
    db: Session, settings: Settings, *, sent: Sent, document_path: str | None = None
) -> SendFeedback:
    """Estado del hilo tras enviar, y el hint que convierte prosa en artefacto.

    Prioridad cuando aplican ambos: gana el del agreement, que es el específico.
    Un `document_path` declarado silencia el hint del agreement (C5): el agente
    ya dijo dónde quedó escrito.
    """
    total = int(
        db.scalar(
            select(func.count()).select_from(Message).where(Message.thread_id == sent.thread.id)
        )
        or 0
    )
    hint: str | None = None
    if (
        sent.message.kind == "agreement"
        and document_path is None
        and not agreement_cited(
            db, project_id=sent.thread.project_id, thread_id=sent.thread.id
        )
    ):
        hint = (
            f"Este acuerdo no está registrado en ningún documento. Si es un "
            f"acuerdo cerrado, apórtalo a 20-contracts/ citando {sent.thread.id} "
            f"en el rationale."
        )
    elif total > settings.thread_long_hint_after and sent.thread.status != "resolved":
        hint = (
            f"Este hilo lleva {total} mensajes abierto. Si alguno de sus temas ya "
            f"cerró, escríbelo a un documento y marca el hilo con resolve."
        )
    return SendFeedback(thread_status=sent.thread.status, thread_message_count=total, hint=hint)


def agreement_cited(db: Session, *, project_id: str, thread_id: str) -> bool:
    """¿Algún rationale del proyecto menciona este hilo?

    No adivina si el acuerdo "cuenta": solo constata que alguien lo citó al
    aportar. `.contains()` genera el LIKE portable (regla 3: nada específico
    del motor).
    """
    return bool(
        db.scalar(
            select(
                exists().where(
                    DocumentVersion.document_id == Document.id,
                    Document.project_id == project_id,
                    DocumentVersion.rationale.contains(thread_id),
                )
            )
        )
    )


def _mark_answered(original: Message) -> None:
    """Un `answer` con `in_reply_to` cierra el mensaje al que responde.

    Es la única vía por la que `answered` es alcanzable: `mesh.py` no tiene
    comando para marcarlo y `api.md` no expone endpoint. Sin esta regla el estado
    sería inalcanzable y el remitente nunca sabría si su pregunta murió o la
    contestaron.

    Solo cierra `kind == "answer"`. Una repregunta (`kind == "question"`) deja el
    original abierto: pedir una aclaración no es responder.
    """
    if original.status != "answered":
        original.status = "answered"


# --------------------------------------------------------------- recirculación


def requeue_orphaned(db: Session, stale: list[AgentSession]) -> list[Message]:
    """Hace volver a circular lo que quedó sin confirmar en sesiones caídas.

    Regla acordada para SPEC §5.5, que dejaba la elección abierta: si el mensaje
    tiene destinatario vuelve a `pending`, para que otra sesión con esa misma
    dirección lo reciba; si no lo tiene, cae a `unclaimed`.

    Un mensaje ya `answered` no se recircula: su ciclo terminó.
    """
    if not stale:
        return []

    huerfanos = list(
        db.scalars(
            select(Message)
            .join(MessageDelivery, MessageDelivery.message_id == Message.id)
            .where(
                MessageDelivery.session_id.in_([s.id for s in stale]),
                MessageDelivery.acked_at.is_(None),
                Message.status != "answered",
            )
            .distinct()
        )
    )
    for message in huerfanos:
        message.claimed_by_session_id = None
        message.claimed_at = None
        message.status = "pending" if message.recipient_address else "unclaimed"
    if huerfanos:
        db.flush()
    return huerfanos


def close_session(db: Session, *, person: Person, session_key: str) -> AgentSession:
    """Cierre limpio de una sesión, con su consecuencia sobre el correo.

    `api.md` es explícito: al cerrar, los mensajes entregados sin `ack` regresan
    a circular. Cerrar sin recircular dejaría esos mensajes esperando a un
    destinatario que ya avisó que se iba, que es peor que no cerrar.

    Vive aquí y no en `services/sessions` porque la recirculación es un hecho de
    la mensajería, y `sessions` no debe saber que existen mensajes. Y no vive en
    el handler porque entonces el invariante dependería de que quien llame se
    acuerde.
    """
    cerrada = sessions.close(db, person=person, session_key=session_key)
    requeue_orphaned(db, [cerrada])
    return cerrada


def refresh(db: Session, settings: Settings, *, project_id: str) -> None:
    """Pone al día el proyecto antes de leer su correo.

    Caduca las sesiones sin latido y recircula lo que dejaron sin confirmar. Es
    el reemplazo de una tarea de fondo: se hace al leer, que es cuando importa.
    """
    caidas = sessions.expire_stale_sessions(db, settings, project_id=project_id)
    requeue_orphaned(db, caidas)


# ---------------------------------------------------------------------- inbox


def _deliverable(
    *, project_id: str, session_id: str, mailbox: str, precise: str
) -> Select[tuple[Message]]:
    """Mensajes que esta sesión puede recibir ahora.

    Incluye los que ya reclamó y todavía no confirmó: reentregar al dueño es
    inofensivo y salva el caso del agente que recibió el mensaje y murió antes de
    hacer `ack`.
    """
    ya_confirmado = exists().where(
        and_(
            MessageDelivery.message_id == Message.id,
            MessageDelivery.session_id == session_id,
            MessageDelivery.acked_at.is_not(None),
        )
    )
    return (
        select(Message)
        .where(
            Message.project_id == project_id,
            Message.status.in_(OPEN_STATUSES),
            Message.recipient_address.in_([mailbox, precise]),
            or_(
                Message.claimed_by_session_id.is_(None),
                Message.claimed_by_session_id == session_id,
            ),
            ~ya_confirmado,
        )
        .order_by(Message.created_at, Message.id)
    )


def try_claim(db: Session, *, message_id: str, session_id: str) -> bool:
    """Reclamo **atómico**. `True` si esta sesión ganó.

    `UPDATE ... WHERE claimed_by_session_id IS NULL` verificando `rowcount`, todo
    dentro de la transacción. Nada de leer-luego-escribir: entre la lectura y la
    escritura cabe otra sesión (regla 4).
    """
    resultado = db.execute(
        update(Message)
        .where(
            Message.id == message_id,
            Message.claimed_by_session_id.is_(None),
        )
        .values(claimed_by_session_id=session_id, claimed_at=utcnow())
    )
    # `Session.execute` está tipado como `Result`, pero un DML siempre devuelve
    # un `CursorResult`, que es el que trae `rowcount`. El cast lo hace explícito
    # en vez de silenciar el chequeo: `rowcount` ES el mecanismo del reclamo.
    return cast("CursorResult[Any]", resultado).rowcount == 1


def collect_inbox(
    db: Session, *, agent_session: AgentSession, mailbox: str, precise: str
) -> list[Message]:
    """Toma para esta sesión lo que le corresponde, reclamando lo que aún no es suyo.

    El inbox pasa por el reclamo atómico, no solo la bandeja de no reclamados. El
    motivo es el buzón del rol: si la misma persona tiene dos sesiones `victor.db`
    —dos terminales, o una huérfana que aún no caduca—, ambas ven el mismo mensaje
    y sin reclamo las dos contestarían la misma pregunta.
    """
    candidatos = list(
        db.scalars(
            _deliverable(
                project_id=agent_session.project_id,
                session_id=agent_session.id,
                mailbox=mailbox,
                precise=precise,
            )
        )
    )

    entregados: list[Message] = []
    for message in candidatos:
        if message.claimed_by_session_id is None and not try_claim(
            db, message_id=message.id, session_id=agent_session.id
        ):
            continue  # otra sesión se adelantó; no es un fallo
        db.refresh(message)
        _record_delivery(db, message=message, session_id=agent_session.id)
        entregados.append(message)

    if entregados:
        db.flush()
    return entregados


def _record_delivery(db: Session, *, message: Message, session_id: str) -> None:
    delivery = db.get(MessageDelivery, (message.id, session_id))
    if delivery is None:
        db.add(MessageDelivery(message_id=message.id, session_id=session_id))
    # `in_progress` y `answered` no se degradan a `delivered`.
    if message.status in ("pending", "unclaimed"):
        message.status = "delivered"


# ------------------------------------------------------- confirmación y avance


def _mine(db: Session, *, agent_session: AgentSession, message_id: str) -> Message:
    """Un mensaje del proyecto de esta sesión. La comprobación es el aislamiento."""
    message = db.get(Message, message_id)
    if message is None or message.project_id != agent_session.project_id:
        raise NotFoundError(f"no existe el mensaje '{message_id}' en este proyecto")
    return message


def ack(db: Session, *, agent_session: AgentSession, message_id: str) -> Message:
    """Confirma recepción. Idempotente: la primera fecha es la que queda."""
    message = _mine(db, agent_session=agent_session, message_id=message_id)
    delivery = db.get(MessageDelivery, (message.id, agent_session.id))
    if delivery is None:
        raise NotFoundError("este mensaje no se te entregó; no hay nada que confirmar")
    if delivery.acked_at is None:
        delivery.acked_at = utcnow()
        db.flush()
    return message


def progress(db: Session, *, agent_session: AgentSession, message_id: str) -> Message:
    """Marca `in_progress` para que el remitente vea "lo están atendiendo"."""
    message = _mine(db, agent_session=agent_session, message_id=message_id)
    if message.claimed_by_session_id != agent_session.id:
        raise NotFoundError("este mensaje no es tuyo; reclámalo primero")
    if message.status not in ("answered",):
        message.status = "in_progress"
        db.flush()
    return message


# ------------------------------------------------- bandeja de no reclamados


def unclaimed_for(db: Session, *, agent_session: AgentSession) -> list[Message]:
    """Mensajes del proyecto que nadie está atendiendo y que esta sesión no descartó.

    La bandeja es más amplia que el estado `unclaimed`: incluye los `pending`
    cuyo destinatario no tiene ninguna sesión viva (§5.3). Un mensaje dirigido a
    `pablo.db` cuando Pablo no ha levantado ese rol sigue esperándolo, y a la vez
    aparece aquí para quien pueda resolverlo.

    La comprobación de "destinatario vivo" se hace en Python y no en SQL porque
    resolver una dirección implica cruzar nombre de persona, rol y sufijo. El
    volumen lo permite de sobra —el servicio mueve unos mensajes por hora— y cada
    dirección distinta se resuelve una sola vez.
    """
    descartados = dismissals_of(db, agent_session.id)

    candidatos = list(
        db.scalars(
            select(Message)
            .where(
                Message.project_id == agent_session.project_id,
                Message.status.in_(("pending", "unclaimed")),
                Message.claimed_by_session_id.is_(None),
                # No tiene sentido reclamar lo que tú mismo enviaste. El
                # `is_(None)` no es adorno: los mensajes que emite el servicio
                # llevan `sender_session_id` nulo, y en SQL `NULL != 'x'` da
                # NULL, no TRUE, así que sin esto los avisos automáticos nunca
                # aparecerían en la bandeja.
                or_(
                    Message.sender_session_id.is_(None),
                    Message.sender_session_id != agent_session.id,
                ),
            )
            .order_by(Message.created_at, Message.id)
        )
    )

    vivos: dict[str, bool] = {}
    salida: list[Message] = []
    for message in candidatos:
        if message.id in descartados:
            continue
        destino = message.recipient_address
        if destino is None:
            salida.append(message)
            continue
        if destino not in vivos:
            vivos[destino] = bool(
                live_recipients(db, project_id=agent_session.project_id, address=destino)
            )
        if not vivos[destino]:
            salida.append(message)
    return salida


def claim(db: Session, *, agent_session: AgentSession, message_id: str) -> Message:
    """Reclama un mensaje de la bandeja. `ConflictError` (409) si otro se adelantó.

    Perder el reclamo **no es un fallo**: significa que ya lo atiende alguien.
    Quien llama decide qué hacer, y `mesh.py` lo distingue con su código de
    salida 2.
    """
    message = _mine(db, agent_session=agent_session, message_id=message_id)

    if message.claimed_by_session_id == agent_session.id:
        return message  # idempotente: ya era suyo
    if not try_claim(db, message_id=message.id, session_id=agent_session.id):
        raise ConflictError(
            "otra sesión reclamó este mensaje antes que tú; ya lo están "
            "atendiendo, sigue adelante"
        )
    db.refresh(message)

    mailbox, precise = addresses_of(db, agent_session)
    dirigido_a_otro = message.recipient_address not in (None, mailbox, precise)

    _record_delivery(db, message=message, session_id=agent_session.id)
    if dirigido_a_otro:
        _notify_sender_of_claim(db, message=message, claimer=precise)
    db.flush()
    return message


def _notify_sender_of_claim(db: Session, *, message: Message, claimer: str) -> None:
    """Avisa al remitente de que su mensaje lo tomó otro rol (§5.3).

    Lo emite el servicio, no una sesión, así que `sender_session_id` va nulo y la
    dirección de origen es la del propio servicio. Va en el mismo hilo y
    respondiendo al mensaje reclamado, para que el remitente lo vea en contexto.

    Es `notice` y no `answer` a propósito: un `answer` cerraría la pregunta, y
    esto no la responde, solo dice quién se hizo cargo.
    """
    db.add(
        Message(
            project_id=message.project_id,
            thread_id=message.thread_id,
            in_reply_to=message.id,
            sender_session_id=None,
            sender_address=SERVICE_ADDRESS,
            recipient_address=message.sender_address,
            kind="notice",
            subject=f"Reclamado por {claimer}: {message.subject}",
            body=(
                f"Tu mensaje iba dirigido a `{message.recipient_address}`, pero "
                f"lo reclamó `{claimer}`, que es quien lo está atendiendo.\n\n"
                f"No hace falta que reenvíes nada."
            ),
            status="pending",
        )
    )


def dismiss(db: Session, *, agent_session: AgentSession, message_id: str) -> Message:
    """Descarte **por sesión**: otras sesiones lo siguen viendo (§5.3).

    Idempotente. No cambia el estado del mensaje: descartar es una opinión de
    esta sesión, no un hecho sobre el mensaje.
    """
    message = _mine(db, agent_session=agent_session, message_id=message_id)
    existente = db.get(MessageDismissal, (message.id, agent_session.id))
    if existente is None:
        db.add(MessageDismissal(message_id=message.id, session_id=agent_session.id))
        db.flush()
    return message


# ----------------------------------------------------------------------- hilos


def thread_with_messages(
    db: Session, *, agent_session: AgentSession, thread_id: str
) -> tuple[Thread, list[Message]]:
    thread = db.get(Thread, thread_id)
    if thread is None or thread.project_id != agent_session.project_id:
        raise NotFoundError(f"no existe el hilo '{thread_id}' en este proyecto")
    mensajes = list(
        db.scalars(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    return thread, mensajes


def resolve_thread(db: Session, *, agent_session: AgentSession, thread_id: str) -> Thread:
    """Marca un hilo como resuelto. Idempotente; 404 fuera del proyecto.

    No hay escritor automático de `resolved` (la nota de enums.py sigue en pie):
    cierra quien sabe que terminó, el agente. Reabrir tampoco necesita permiso:
    un send al hilo resuelto lo regresa a `open` (ver `_resolve_thread`).
    """
    thread = db.get(Thread, thread_id)
    if thread is None or thread.project_id != agent_session.project_id:
        raise NotFoundError(f"no existe el hilo '{thread_id}' en este proyecto")
    if thread.status != "resolved":
        thread.status = "resolved"
        thread.updated_at = utcnow()
        db.flush()
    return thread


def _message_counts() -> Any:
    """Subconsulta de conteo de mensajes por hilo, para las vistas de hilos."""
    return (
        select(Message.thread_id, func.count().label("total"))
        .group_by(Message.thread_id)
        .subquery()
    )


def threads_overview(
    db: Session, *, project_id: str, status: str | None = None
) -> list[tuple[Thread, int]]:
    """Hilos del proyecto con su conteo, los más recientes primero."""
    conteo = _message_counts()
    query = (
        select(Thread, func.coalesce(conteo.c.total, 0))
        .outerjoin(conteo, conteo.c.thread_id == Thread.id)
        .where(Thread.project_id == project_id)
        .order_by(Thread.updated_at.desc(), Thread.id)
    )
    if status is not None:
        query = query.where(Thread.status == status)
    return [(hilo, int(total)) for hilo, total in db.execute(query)]


def oldest_open_threads(
    db: Session, *, project_id: str, limit: int = 5
) -> list[tuple[Thread, int]]:
    """Los hilos sin resolver más viejos. C4 los inyecta en el inbox."""
    conteo = _message_counts()
    query = (
        select(Thread, func.coalesce(conteo.c.total, 0))
        .outerjoin(conteo, conteo.c.thread_id == Thread.id)
        .where(Thread.project_id == project_id, Thread.status != "resolved")
        .order_by(Thread.updated_at.asc(), Thread.id)
        .limit(limit)
    )
    return [(hilo, int(total)) for hilo, total in db.execute(query)]


def open_thread_count(db: Session, *, project_id: str) -> int:
    """Hilos "abiertos" = no resueltos (incluye in_progress)."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(Thread)
            .where(Thread.project_id == project_id, Thread.status != "resolved")
        )
        or 0
    )


def dismissals_of(db: Session, session_id: str) -> set[str]:
    """Ids que esta sesión ya descartó. El paso 6 lo usa para la bandeja."""
    return set(
        db.scalars(
            select(MessageDismissal.message_id).where(MessageDismissal.session_id == session_id)
        )
    )
