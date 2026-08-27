"""Proyectos, membresías y sesiones de agente.

El proyecto es la frontera dura de aislamiento (CLAUDE.md, regla 2). Casi toda
tabla del sistema cuelga de `project_id` justamente para que ninguna consulta
pueda cruzarla por descuido.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import enums, ids
from app.db.base import Base, utcnow


class Project(Base):
    """El "cuarto". Lo crea un administrador desde el panel, nunca un agente.

    No existe `POST /projects` ni auto-inscripción en la API de agentes, ni
    siquiera por conveniencia en desarrollo (regla 9, SPEC §3.1).
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.PROJECT)
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMember(Base):
    """Quién participa en un proyecto. Decisión de personas, no de agentes.

    La clave compuesta es la que garantiza que no haya membresías duplicadas.
    """

    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentSession(Base):
    """Una instancia viva de agente, con un rol como etiqueta.

    Se llama `AgentSession` y no `Session` para no chocar con la sesión de
    SQLAlchemy; la tabla sí es `sessions`, como en SPEC §7.

    El `role_label` es una etiqueta de dirección, **no un contrato de
    responsabilidades**: un agente que hace de todo registra `general` y funciona
    igual. Por eso no hay catálogo de roles ni FK: es texto libre.

    Puede haber dos sesiones vivas con el mismo `persona.rol`; en ese caso el
    mensaje se ofrece a ambas y decide el reclamo atómico (SPEC §3).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            enums.sql_in("status", enums.SESSION_STATUSES),
            name="status_valido",
        ),
        # SPEC §7: resolver `persona.rol` dentro de un proyecto es la consulta
        # caliente del enrutado.
        Index("ix_sessions_project_person_role", "project_id", "person_id", "role_label"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.SESSION)
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), index=True
    )
    role_label: Mapped[str] = mapped_column(String(64))
    # Viaja en la cabecera X-Mesh-Session. No es la credencial (esa es el token
    # de la persona), pero no debe ser adivinable.
    session_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Sin heartbeat durante SESSION_STALE_AFTER_SECONDS la sesión pasa a `stale`
    # y sus mensajes sin ack vuelven a circular.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
