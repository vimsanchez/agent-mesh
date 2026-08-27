"""Valores cerrados del dominio.

Se guardan como texto con `CheckConstraint`, no como el tipo ENUM del motor:
SQLite no lo tiene y en Postgres cambiar un ENUM exige DDL propio. Con texto +
check, migrar es cambiar `DATABASE_URL` (regla 3 de `CLAUDE.md`).

`Literal` da el chequeo estático; las tuplas alimentan los constraints.
"""

from typing import Final, Literal

# --------------------------------------------------------------------- mensajes

MessageKind = Literal["question", "answer", "notice", "proposal", "agreement"]
MESSAGE_KINDS: Final[tuple[str, ...]] = (
    "question",
    "answer",
    "notice",
    "proposal",
    "agreement",
)

# Los cinco estados de SPEC.md §5.2, ni uno más:
#
#   pending ──delivered──▶ delivered ──progress──▶ in_progress ──answer──▶ answered
#      │                       │
#      │                       └── (sesión destino muere / stale) ──▶ unclaimed
#      └── (rol destino no existe) ──▶ unclaimed
#
# `ack` NO aparece aquí a propósito. Confirmar recepción es un hecho de la
# *entrega*, no del mensaje: vive en `message_deliveries.acked_at`. Una misma
# pregunta puede ofrecerse a dos sesiones con la misma dirección, y cada una
# tiene su propio ack. Por eso `ack` no mueve el estado y `progress` sí.
MessageStatus = Literal["pending", "delivered", "in_progress", "answered", "unclaimed"]
MESSAGE_STATUSES: Final[tuple[str, ...]] = (
    "pending",
    "delivered",
    "in_progress",
    "answered",
    "unclaimed",
)

# ---------------------------------------------------------------------- sesiones

SessionStatus = Literal["active", "stale", "closed"]
SESSION_STATUSES: Final[tuple[str, ...]] = ("active", "stale", "closed")

# ------------------------------------------------------------------------ hilos

# `resolved` no tiene escritor automático en esta etapa: un hilo aguanta varias
# preguntas y cerrarlo con la primera respuesta sería mentir. Existe desde ahora
# porque el campo está en SPEC §7 (regla 8).
ThreadStatus = Literal["open", "in_progress", "resolved"]
THREAD_STATUSES: Final[tuple[str, ...]] = ("open", "in_progress", "resolved")

# ------------------------------------------------------------------ documentos

DocumentStatus = Literal["active", "archived"]
DOCUMENT_STATUSES: Final[tuple[str, ...]] = ("active", "archived")

ContributionIntent = Literal["create", "append", "amend", "deprecate"]
CONTRIBUTION_INTENTS: Final[tuple[str, ...]] = ("create", "append", "amend", "deprecate")

# ----------------------------------------------------------------------- panel

# SPEC §9 pide que la tabla y el campo existan desde el día uno, pero no fija los
# valores. Estos dos son la apuesta mínima; la interfaz de gestión llega después.
AdminRole = Literal["owner", "admin"]
ADMIN_ROLES: Final[tuple[str, ...]] = ("owner", "admin")


def sql_in(column: str, values: tuple[str, ...]) -> str:
    """Expresión `col IN (...)` para un CheckConstraint.

    No se interpola con `f"{tupla}"` porque el repr de una tupla de un solo
    elemento en Python es `('x',)`, y esa coma sobrante es SQL inválido. Aquí
    también se citan los valores de forma explícita.
    """
    if not values:
        msg = f"lista de valores vacía para {column}"
        raise ValueError(msg)
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"
