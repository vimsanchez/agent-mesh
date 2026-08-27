"""Documentos de conocimiento y su historial inmutable.

Los agentes no editan archivos: mandan aportaciones y el servicio guarda la
versión completa resultante (CLAUDE.md, regla 5). Nada se sobrescribe a ciegas y
nada se borra: `deprecate` mueve el bloque a `## Obsoleto` con autor y motivo.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import enums, ids
from app.db.base import Base, utcnow


class Document(Base):
    """Un documento del proyecto, identificado por su `path`.

    El contenido no vive aquí sino en `document_versions`: esta fila solo apunta
    a cuál es la versión vigente. Así el historial es inmutable por construcción.

    El `path` sigue la convención jerárquica de SPEC §6.2
    (`00-conventions/`, `10-architecture/`, `20-contracts/`, `30-decisions/`,
    `90-scratch/`), pero no se valida contra una lista cerrada: es convención,
    no esquema.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            enums.sql_in("status", enums.DOCUMENT_STATUSES),
            name="status_valido",
        ),
        # SPEC §7: único. Dos documentos con la misma ruta en un proyecto harían
        # ambiguo `GET /docs?path=...`.
        UniqueConstraint("project_id", "path", name="uq_documents_project_path"),
        Index("ix_documents_project_path", "project_id", "path"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.DOCUMENT)
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(400))
    title: Mapped[str] = mapped_column(String(300), default="")
    # La versión que un agente debe declarar como `base_version` para aportar.
    # Si no coincide -> 409 con la versión vigente.
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DocumentVersion(Base):
    """Una versión completa del documento. Inmutable.

    Se guarda el contenido entero, no un diff: reconstruir el estado a partir de
    una cadena de parches es frágil y aquí el volumen es diminuto.

    `author_address` se congela como texto (`persona.rol`) para que el historial
    siga siendo legible aunque la sesión que aportó ya no exista.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            enums.sql_in("intent", enums.CONTRIBUTION_INTENTS),
            name="intent_valido",
        ),
        # Dos filas con la misma versión de un documento romperían el control de
        # concurrencia optimista.
        UniqueConstraint("document_id", "version", name="uq_document_versions_doc_version"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.VERSION)
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(16))
    # Por qué se aportó. Lo que evita que dentro de dos semanas se renegocie algo
    # ya acordado sin saber que se acordó.
    rationale: Mapped[str] = mapped_column(Text, default="")
    author_address: Mapped[str] = mapped_column(String(130))
    author_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
