"""Formas de entrada y salida de la API de agentes.

Los nombres de campo son los de `references/api.md`, no los de los modelos: es lo
que `mesh.py` ya espera y ese cliente no se rediseña.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.enums import ContributionIntent, MessageKind

# ------------------------------------------------------------------ proyectos


class ProjectOut(BaseModel):
    slug: str
    name: str
    members: list[str] = Field(
        description="Nombres de las personas miembro, no direcciones de agente."
    )


class ProjectsOut(BaseModel):
    """Respuesta de `GET /projects`.

    Una lista vacía es válida y significa "todavía no te agregan a ninguno". No
    es un error, y el agente debe detenerse y reportarlo.
    """

    person: str
    projects: list[ProjectOut]


# -------------------------------------------------------------------- sesiones


class RegisterIn(BaseModel):
    project: str
    role: str


class SessionOut(BaseModel):
    session_key: str
    address: str = Field(
        description="Buzón del rol: 'persona.rol'. Es la dirección estable y la "
        "que se cita en los acuerdos."
    )
    session_address: str = Field(
        description="Esta sesión concreta: 'persona.rol.sufijo'. Sirve para que "
        "una réplica vuelva a quien atendió, no para apuntarla a largo plazo: "
        "cambia en cada register."
    )
    project: str
    registered_at: datetime
    conventions: str | None = Field(
        default=None,
        description="Contenido íntegro de 00-conventions/messaging.md, o null si "
        "no existe. Léelas y cúmplelas: son las reglas de este proyecto.",
    )
    open_threads: int = 0


class HeartbeatOut(BaseModel):
    address: str
    status: str
    last_seen_at: datetime


class ClosedOut(BaseModel):
    address: str
    status: str


class RosterEntry(BaseModel):
    address: str
    session_address: str = Field(
        description="Distingue dos sesiones de la misma persona con el mismo rol."
    )
    status: str
    last_seen_at: datetime


class RosterOut(BaseModel):
    sessions: list[RosterEntry]


# -------------------------------------------------------------------- mensajes


class SendIn(BaseModel):
    to: str | None = Field(
        default=None,
        description="'persona.rol' o 'persona.rol.sufijo'. Omitirlo hace que el "
        "mensaje nazca en la bandeja de no reclamados.",
    )
    kind: MessageKind = "question"
    subject: str
    body: str = ""
    in_reply_to: str | None = None
    thread_id: str | None = None


class SentOut(BaseModel):
    """C2 de SPEC-DELTA: el send contesta con el estado de la conversación.

    `hint` es null salvo dos casos: un agreement cuyo hilo nadie citó al
    aportar, o un hilo que superó THREAD_LONG_HINT_AFTER mensajes sin
    resolverse.
    """

    id: str
    thread_id: str
    status: str
    thread_status: str
    thread_message_count: int
    hint: str | None = None


class MessageOut(BaseModel):
    id: str
    thread_id: str
    in_reply_to: str | None
    sender: str = Field(serialization_alias="from", validation_alias="from")
    to: str | None
    kind: str
    subject: str
    body: str
    status: str
    created_at: datetime

    model_config = {"populate_by_name": True}


class OpenThreadRef(BaseModel):
    id: str
    subject: str
    updated_at: datetime
    message_count: int


class InboxContext(BaseModel):
    """Solo presente cuando la respuesta trae mensajes: una respuesta vacía de
    long poll se queda `{"messages": []}` para no meter ruido en el monitor."""

    open_threads: int
    oldest_open: list[OpenThreadRef]


class InboxOut(BaseModel):
    """Lista vacía = no hay nada nuevo *ahora*.

    No dice nada sobre cuánto tarda el otro agente en pensar (SPEC §5.4).
    """

    messages: list[MessageOut]
    context: InboxContext | None = None


class AckOut(BaseModel):
    """C1 de SPEC-DELTA: el momento del ack es cuando el mensaje desaparece del
    inbox; la respuesta conserva la llave del hilo para `GET /threads/{id}`."""

    id: str
    status: str
    acked: bool
    thread_id: str
    thread_status: str
    subject: str


class ProgressOut(BaseModel):
    id: str
    status: str


class ThreadOut(BaseModel):
    id: str
    subject: str
    status: str
    messages: list[MessageOut]


class ThreadResolvedOut(BaseModel):
    id: str
    subject: str
    status: str


class ThreadSummary(BaseModel):
    id: str
    subject: str
    status: str
    message_count: int
    updated_at: datetime


class ThreadsOut(BaseModel):
    """Respuesta de `GET /threads` (C3). El criterio objetivo de cierre de canal
    que los agentes inventaron a mano: bandeja vacía en los dos sentidos."""

    threads: list[ThreadSummary]


class UnclaimedOut(BaseModel):
    """Bandeja de no reclamados, ya filtrada por lo que esta sesión descartó."""

    messages: list[MessageOut]


class ClaimOut(BaseModel):
    id: str
    status: str
    claimed: bool


class DismissOut(BaseModel):
    id: str
    dismissed: bool


# ------------------------------------------------------------------ documentos


class DocumentIndexEntry(BaseModel):
    id: str
    path: str
    title: str
    current_version: int
    updated_at: datetime


class DocumentIndexOut(BaseModel):
    documents: list[DocumentIndexEntry]


class DocumentOut(BaseModel):
    id: str
    path: str
    title: str
    current_version: int = Field(
        description="Guarda este número: lo necesitas como base_version para aportar."
    )
    content: str
    status: str
    updated_at: datetime


class ContributeIn(BaseModel):
    document_path: str
    base_version: int
    intent: ContributionIntent
    anchor: str | None = None
    content: str = ""
    rationale: str


class VersionEntry(BaseModel):
    version: int
    intent: str
    rationale: str
    author_address: str
    created_at: datetime


class VersionsOut(BaseModel):
    document_id: str
    path: str
    versions: list[VersionEntry]
