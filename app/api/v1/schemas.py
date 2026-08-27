"""Formas de entrada y salida de la API de agentes.

Los nombres de campo son los de `references/api.md`, no los de los modelos: es lo
que `mesh.py` ya espera y ese cliente no se rediseña.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.enums import MessageKind

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
    id: str
    thread_id: str
    status: str


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


class InboxOut(BaseModel):
    """Lista vacía = no hay nada nuevo *ahora*.

    No dice nada sobre cuánto tarda el otro agente en pensar (SPEC §5.4).
    """

    messages: list[MessageOut]


class AckOut(BaseModel):
    id: str
    status: str
    acked: bool


class ProgressOut(BaseModel):
    id: str
    status: str


class ThreadOut(BaseModel):
    id: str
    subject: str
    status: str
    messages: list[MessageOut]
