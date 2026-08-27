"""Modelos ORM. Las 12 tablas de SPEC.md §7.

Todas existen desde el primer commit aunque varias no se usen todavía
(CLAUDE.md, regla 8): así no hay migraciones dolorosas después.

Importarlas aquí es lo que las registra en `Base.metadata`, que es de donde
Alembic saca el esquema.
"""

from app.db.models.identity import AccessToken, AdminUser, Person
from app.db.models.knowledge import Document, DocumentVersion
from app.db.models.messaging import Message, MessageDelivery, MessageDismissal, Thread
from app.db.models.projects import AgentSession, Project, ProjectMember

__all__ = [
    "AccessToken",
    "AdminUser",
    "AgentSession",
    "Document",
    "DocumentVersion",
    "Message",
    "MessageDelivery",
    "MessageDismissal",
    "Person",
    "Project",
    "ProjectMember",
    "Thread",
]
