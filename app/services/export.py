"""Exportación a Markdown de hilos y documentos, para el panel.

Es lectura pura: no cambia estados, no registra descargas. Existe para que una
persona pueda llevarse lo que los agentes acordaron —a un repo, a una nota, a
otro sitio— desde cualquier dispositivo con solo entrar al panel.

Dos reglas de forma:

- Un **hilo** se genera: cabecera con el asunto y el estado, y un bloque por
  mensaje con remitente, destinatario, tipo y fecha. Es la transcripción de una
  conversación que no existía como archivo.
- Un **documento** sale **tal cual**: ya es Markdown y la idea es que sirva
  pegado en un repo. Su metadata (versión, estado, fecha) va al `INDEX.md` del
  zip, no encima del contenido.

La frontera de proyecto no se decide aquí: quien llama ya resolvió el proyecto y
carga solo lo que le pertenece. Estas funciones son puras sobre lo que reciben.
"""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, Message, Project, Thread
from app.services import knowledge

_MAX_SLUG = 48


@dataclass(frozen=True)
class DocumentInfo:
    """Lo que el índice necesita saber de un documento, sin arrastrar el ORM."""

    path: str
    title: str
    version: int
    status: str
    updated_at: datetime


ThreadBundle = tuple[Thread, list[Message]]
DocumentBundle = tuple[DocumentInfo, str]


# ------------------------------------------------------------------- nombres


def slugify(text: str) -> str:
    """ASCII seguro para nombres de archivo y cabeceras HTTP."""
    plano = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    limpio = re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-")
    return limpio[:_MAX_SLUG].rstrip("-") or "sin-asunto"


def thread_filename(thread: Thread) -> str:
    """Fecha + asunto + cola del id: legible al ojo y único aunque dos hilos
    compartan asunto."""
    return f"{thread.created_at:%Y-%m-%d}-{slugify(thread.subject)}-{thread.id[-4:]}.md"


def document_filename(path: str) -> str:
    return path.rsplit("/", 1)[-1] or "documento.md"


# ------------------------------------------------------------------ markdown


def _stamp(momento: datetime) -> str:
    return f"{momento:%Y-%m-%d %H:%M}Z"


def thread_markdown(project: Project, thread: Thread, messages: list[Message]) -> str:
    cuantos = len(messages)
    lineas = [
        f"# {thread.subject}",
        "",
        f"Proyecto: {project.slug} · Hilo: {thread.id} · Estado: {thread.status} · "
        f"{cuantos} mensaje{'s' if cuantos != 1 else ''} · "
        f"{_stamp(thread.created_at)} → {_stamp(thread.updated_at)}",
        "",
    ]
    for n, message in enumerate(messages, start=1):
        destino = message.recipient_address or "(sin destinatario)"
        lineas += [
            f"## {n}. {message.sender_address} → {destino} · {message.kind} · "
            f"{_stamp(message.created_at)}",
            "",
        ]
        if message.subject and message.subject != thread.subject:
            lineas += [f"### {message.subject}", ""]
        lineas += [message.body.rstrip("\n"), ""]
    return "\n".join(lineas).rstrip("\n") + "\n"


def document_markdown(content: str) -> str:
    """Tal cual. Solo garantiza el salto de línea final si hay contenido."""
    if not content:
        return ""
    return content.rstrip("\n") + "\n"


def index_markdown(
    project: Project,
    threads: list[ThreadBundle] | None,
    documents: list[DocumentBundle] | None,
) -> str:
    """Portada del zip. `None` en una sección significa que no se pidió."""
    lineas = [
        f"# {project.name} ({project.slug})",
        "",
        f"Exportado de Agent Mesh el {_stamp(datetime.now(UTC))}.",
        "",
    ]
    if threads is not None:
        lineas += ["## Hilos", ""]
        if threads:
            lineas += [
                "| Asunto | Estado | Mensajes | Última actividad | Archivo |",
                "|---|---|---|---|---|",
            ]
            for thread, messages in threads:
                lineas.append(
                    f"| {_cell(thread.subject)} | {thread.status} | {len(messages)} | "
                    f"{_stamp(thread.updated_at)} | `threads/{thread_filename(thread)}` |"
                )
        else:
            lineas.append("Todavía no hay hilos en este proyecto.")
        lineas.append("")
    if documents is not None:
        lineas += ["## Documentos", ""]
        if documents:
            lineas += [
                "| Ruta | Título | Versión | Estado | Actualizado |",
                "|---|---|---|---|---|",
            ]
            for info, _ in documents:
                lineas.append(
                    f"| `docs/{info.path}` | {_cell(info.title)} | v{info.version} | "
                    f"{info.status} | {_stamp(info.updated_at)} |"
                )
        else:
            lineas.append("Todavía no hay documentos en este proyecto.")
        lineas.append("")
    return "\n".join(lineas).rstrip("\n") + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


# ----------------------------------------------------------------------- zip


def project_zip(
    project: Project,
    *,
    threads: list[ThreadBundle] | None,
    documents: list[DocumentBundle] | None,
) -> bytes:
    """Zip en memoria. Es texto: ni un proyecto grande pasa de unos MB.

    `None` en `threads` o `documents` deja esa parte fuera (zips parciales);
    una lista vacía la incluye y el índice dice que no hay nada.
    """
    buffer = io.BytesIO()
    raiz = project.slug
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{raiz}/INDEX.md", index_markdown(project, threads, documents))
        for thread, messages in threads or []:
            z.writestr(
                f"{raiz}/threads/{thread_filename(thread)}",
                thread_markdown(project, thread, messages),
            )
        for info, content in documents or []:
            z.writestr(f"{raiz}/docs/{info.path}", document_markdown(content))
    return buffer.getvalue()


# ------------------------------------------------------------------- cargas


def threads_of(db: Session, project: Project) -> list[ThreadBundle]:
    """Todos los hilos del proyecto con sus mensajes en orden cronológico."""
    hilos = list(
        db.scalars(
            select(Thread)
            .where(Thread.project_id == project.id)
            .order_by(Thread.created_at, Thread.id)
        )
    )
    mensajes = list(
        db.scalars(
            select(Message)
            .where(Message.project_id == project.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    por_hilo: dict[str, list[Message]] = {thread.id: [] for thread in hilos}
    for message in mensajes:
        por_hilo.setdefault(message.thread_id, []).append(message)
    return [(thread, por_hilo[thread.id]) for thread in hilos]


def messages_of(db: Session, thread: Thread) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at, Message.id)
        )
    )


def info_of(document: Document) -> DocumentInfo:
    return DocumentInfo(
        path=document.path,
        title=document.title,
        version=document.current_version,
        status=document.status,
        updated_at=document.updated_at,
    )


def documents_of(db: Session, project: Project) -> list[DocumentBundle]:
    return [
        (info_of(document), knowledge.current_content(db, document))
        for document in knowledge.index(db, project_id=project.id)
    ]
