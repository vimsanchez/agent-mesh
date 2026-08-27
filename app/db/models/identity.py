"""Identidad: administradores del panel, personas y sus tokens.

Dos poblaciones distintas que no se mezclan. `admin_users` entra por el panel con
correo y contraseña; `people` no entra a ningún lado: es a quien representa un
token de agente. Un administrador no es automáticamente una persona.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import enums, ids
from app.db.base import Base, utcnow
from app.db.types import UtcDateTime


class AdminUser(Base):
    """Usuario del panel de administración (SPEC §9)."""

    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            enums.sql_in("role", enums.ADMIN_ROLES),
            name="role_valido",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.ADMIN)
    )
    # El dominio se valida contra ADMIN_EMAIL_DOMAIN en la capa de servicio,
    # nunca contra PUBLIC_SERVICE_DOMAIN (CLAUDE.md, regla 6).
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Argon2id. Jamás texto plano, jamás en logs, jamás en respuestas (regla 7).
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)


class Person(Base):
    """El humano dueño de una cuenta de agente. Se autentica con token."""

    __tablename__ = "people"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.PERSON)
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Primer componente de la dirección pública `persona.rol`.
    display_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class AccessToken(Base):
    """Token personal. Identifica a la persona, no a la sesión.

    Se guarda solo el hash. El valor en claro se muestra una vez al emitirlo en
    el panel y nunca se puede recuperar: la API no ofrece endpoint para leerlo,
    rotarlo ni consultarlo (`references/api.md`).

    Varios agentes de la misma persona comparten el mismo token y obtienen
    sesiones distintas, así que un token puede tener N sesiones vivas.
    """

    __tablename__ = "access_tokens"

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: ids.new_id(ids.TOKEN)
    )
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Revocar no borra: se conserva el rastro de qué token existió.
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
