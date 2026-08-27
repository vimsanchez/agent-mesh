"""Constructores mínimos para las pruebas de esquema.

Solo rellenan lo obligatorio. La lógica de dominio (direcciones, hilos, reclamo)
llega en los pasos 4 a 7; aquí únicamente se necesita que las filas existan para
poder empujar los constraints.
"""

from sqlalchemy.orm import Session

from app.db import ids
from app.db.models import (
    AgentSession,
    Document,
    Message,
    Person,
    Project,
    Thread,
)


def make_project(db: Session, slug: str = "proyecto-pablo") -> Project:
    project = Project(slug=slug, name=f"Proyecto {slug}")
    db.add(project)
    db.flush()
    return project


def make_person(db: Session, name: str = "victor") -> Person:
    person = Person(email=f"{name}@ejemplo.test", display_name=name)
    db.add(person)
    db.flush()
    return person


def make_session(
    db: Session, project: Project, person: Person, role: str = "db"
) -> AgentSession:
    agent_session = AgentSession(
        project_id=project.id,
        person_id=person.id,
        role_label=role,
        session_key=ids.new_session_key(),
    )
    db.add(agent_session)
    db.flush()
    return agent_session


def make_thread(db: Session, project: Project, subject: str = "Contrato") -> Thread:
    thread = Thread(project_id=project.id, subject=subject)
    db.add(thread)
    db.flush()
    return thread


def make_message(
    db: Session,
    project: Project,
    thread: Thread,
    *,
    sender: str = "victor.db",
    recipient: str | None = "pablo.general",
    kind: str = "question",
    status: str = "pending",
) -> Message:
    message = Message(
        project_id=project.id,
        thread_id=thread.id,
        sender_address=sender,
        recipient_address=recipient,
        kind=kind,
        subject="¿cursor u offset?",
        body="…markdown…",
        status=status,
    )
    db.add(message)
    db.flush()
    return message


def make_document(
    db: Session, project: Project, path: str = "20-contracts/api-orders.md"
) -> Document:
    document = Document(project_id=project.id, path=path, title="API de pedidos")
    db.add(document)
    db.flush()
    return document
