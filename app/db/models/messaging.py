"""Hilos, mensajes y el rastro de entrega.

`messages` es la tabla caliente del sistema. Sus dos índices existen para las dos
consultas que se repiten sin parar: el inbox de una dirección y la bandeja de no
reclamados del proyecto (SPEC §7).
"""

from datetime import datetime

from sqlalchemy import (
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


class Thread(Base):
    """Conversación. Se crea sola con el primer mensaje que no responde a nada."""

    __tablename__ = "threads"
    __table_args__ = (
        CheckConstraint(
            enums.sql_in("status", enums.THREAD_STATUSES),
            name="status_valido",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.THREAD)
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(300))
    # `resolved` no tiene escritor automático en esta etapa: un hilo aguanta
    # varias preguntas y cerrarlo con la primera respuesta sería mentir.
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Message(Base):
    """Un mensaje entre sesiones de agentes.

    `recipient_address` es texto (`persona.rol`) y no una FK a `sessions`
    a propósito: escribirle a un rol que todavía nadie levantó **no es error**,
    el mensaje espera (SPEC §5.2). Una FK lo haría imposible.

    `sender_session_id` es opcional porque el propio servicio emite mensajes: al
    reclamar algo dirigido a otro rol se manda un `notice` automático al
    remitente (SPEC §5.3), y detrás de ese mensaje no hay ninguna sesión.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(enums.sql_in("kind", enums.MESSAGE_KINDS), name="kind_valido"),
        CheckConstraint(
            enums.sql_in("status", enums.MESSAGE_STATUSES),
            name="status_valido",
        ),
        # Inbox: "lo dirigido a esta dirección que sigue pendiente".
        Index(
            "ix_messages_project_recipient_status",
            "project_id",
            "recipient_address",
            "status",
        ),
        # Bandeja de no reclamados del proyecto.
        Index("ix_messages_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.MESSAGE)
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    in_reply_to: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    sender_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    # Se congela al enviar. Si la sesión muere, el mensaje sigue diciendo de
    # quién vino; por eso se guarda el texto y no solo la FK.
    sender_address: Mapped[str] = mapped_column(String(130))
    # `null` -> el mensaje nace directamente en la bandeja de no reclamados.
    recipient_address: Mapped[str | None] = mapped_column(String(130))
    kind: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(300))
    # Markdown, y se espera que sea largo: sustituye a los .md que hoy se pasan
    # por Telegram.
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    claimed_by_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageDelivery(Base):
    """Rastro de entrega por sesión. Es donde vive el `ack`.

    Confirmar recepción es un hecho de la *entrega*, no del mensaje: si una misma
    dirección tiene dos sesiones vivas, cada una tiene su propio ack. Por eso
    `ack` no aparece en `messages.status`.

    Si una sesión muere sin hacer ack dentro de SESSION_STALE_AFTER_SECONDS, el
    mensaje vuelve a circular (SPEC §5.5).
    """

    __tablename__ = "message_deliveries"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageDismissal(Base):
    """Descarte por sesión: "yo ya lo vi y no me toca".

    Es por sesión y no global a propósito: otras sesiones lo siguen viendo en la
    bandeja de no reclamados (SPEC §5.3).
    """

    __tablename__ = "message_dismissals"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
