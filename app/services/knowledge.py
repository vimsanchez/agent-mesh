"""Conocimiento: documentos, aportaciones y versionado.

**Los agentes no editan archivos.** Mandan una aportación, el servicio la aplica y
guarda la **versión completa resultante** (regla 5). Nunca se sobrescribe a
ciegas y nunca se borra nada: `deprecate` marca como obsoleto.

Por qué versión completa y no diff: reconstruir el estado a partir de una cadena
de parches es frágil y aquí el volumen es diminuto. El historial es inmutable por
construcción, no por disciplina.
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app.db.models import AgentSession, Document, DocumentVersion
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError

OBSOLETE_HEADING = "## Obsoleto"


@dataclass(frozen=True)
class Contribution:
    document: Document
    version: DocumentVersion


class VersionConflictError(ConflictError):
    """`base_version` no es la vigente.

    Lleva la versión actual y el contenido vigente porque el agente los necesita
    para reconciliar: `api.md` promete que el 409 trae ambos, y sin ellos el
    agente solo puede reintentar a ciegas.
    """

    def __init__(self, *, current_version: int, content: str) -> None:
        self.current_version = current_version
        self.content = content
        super().__init__(
            f"el documento ya está en la versión {current_version} y tú trabajaste "
            f"sobre otra; relee, reconcilia tu aporte con lo nuevo y reintenta. "
            f"No reintentes con la misma base_version."
        )


# ------------------------------------------------------------------- lectura


def index(db: Session, *, project_id: str) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.project_id == project_id).order_by(Document.path)
        )
    )


def by_path(db: Session, *, project_id: str, path: str) -> Document:
    document = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.path == path.strip())
    )
    if document is None:
        raise NotFoundError(
            f"no existe el documento '{path}' en este proyecto; para crearlo, "
            f"aporta con intent=create y base_version=0"
        )
    return document


def current_content(db: Session, document: Document) -> str:
    """Contenido vigente. Cadena vacía si todavía no hay ninguna versión."""
    if document.current_version == 0:
        return ""
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == document.current_version,
        )
    )
    return version.content if version is not None else ""


def history_of(db: Session, document: Document) -> list[DocumentVersion]:
    """Historial de un documento ya validado por quien llama.

    Existe para el panel, que resuelve la pertenencia por proyecto y no por
    sesión de agente. La validación no se salta: se hace antes, en el handler.
    """
    return list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version)
        )
    )


def history(
    db: Session, *, agent_session: AgentSession, document_id: str
) -> tuple[Document, list[DocumentVersion]]:
    """Historial completo. Devuelve el documento porque ya se cargó para validar
    pertenencia y quien llama lo necesita para responder."""
    document = db.get(Document, document_id)
    if document is None or document.project_id != agent_session.project_id:
        raise NotFoundError(f"no existe el documento '{document_id}' en este proyecto")
    return document, history_of(db, document)


# ------------------------------------------------------- aplicar la aportación


def _split_sections(content: str) -> list[tuple[str | None, list[str]]]:
    """Parte el markdown en (encabezado, líneas) por cada `##`.

    El primer bloque puede no tener encabezado: es el preámbulo del documento, y
    se representa con `None` para no perderlo al reescribir.
    """
    secciones: list[tuple[str | None, list[str]]] = []
    actual: tuple[str | None, list[str]] = (None, [])
    for linea in content.splitlines():
        if linea.startswith("## "):
            if actual[0] is not None or actual[1]:
                secciones.append(actual)
            actual = (linea.rstrip(), [])
        else:
            actual[1].append(linea)
    if actual[0] is not None or actual[1]:
        secciones.append(actual)
    return secciones


def _join_sections(secciones: list[tuple[str | None, list[str]]]) -> str:
    partes: list[str] = []
    for encabezado, lineas in secciones:
        if encabezado is not None:
            partes.append(encabezado)
        partes.extend(lineas)
    return "\n".join(partes).strip() + "\n"


def _find_anchor(secciones: list[tuple[str | None, list[str]]], anchor: str) -> int:
    buscado = anchor.strip()
    for indice, (encabezado, _) in enumerate(secciones):
        if encabezado is not None and encabezado.strip() == buscado:
            return indice
    disponibles = [e for e, _ in secciones if e is not None]
    raise ValidationFailedError(
        f"no encuentro el ancla '{anchor}' en el documento. "
        f"Encabezados disponibles: {disponibles or 'ninguno'}"
    )


def apply_intent(
    *,
    content: str,
    intent: str,
    anchor: str | None,
    aporte: str,
    author_address: str,
    rationale: str,
) -> str:
    """Calcula el contenido resultante. Función pura: no toca la base.

    Separarla del guardado es lo que permite probar las cuatro intenciones sin
    montar un proyecto entero, y garantiza que la versión guardada es exactamente
    lo que esta función devolvió.
    """
    if intent == "create":
        return aporte.strip() + "\n"

    if intent == "append":
        # El ancla se ignora a propósito: añadir es al final del documento. Si
        # alguien quiere añadir dentro de una sección, eso es `amend`.
        base = content.rstrip()
        return f"{base}\n\n{aporte.strip()}\n" if base else aporte.strip() + "\n"

    if anchor is None:
        raise ValidationFailedError(
            f"intent={intent} necesita --anchor: es el encabezado sobre el que se opera"
        )

    secciones = _split_sections(content)
    indice = _find_anchor(secciones, anchor)

    if intent == "amend":
        encabezado, _ = secciones[indice]
        secciones[indice] = (encabezado, ["", *aporte.strip().splitlines(), ""])
        return _join_sections(secciones)

    if intent == "deprecate":
        # No borra: mueve el bloque al final bajo `## Obsoleto` con autor y motivo
        # (§6.3). Borrarlo perdería el porqué de una decisión que alguien tomó.
        encabezado, lineas = secciones.pop(indice)
        nota = [
            "",
            f"### {str(encabezado).removeprefix('## ').strip()}",
            f"*Marcado obsoleto por {author_address}: {rationale.strip()}*",
            "",
            *[linea for linea in lineas if linea.strip()],
            "",
        ]
        existente = next(
            (i for i, (e, _) in enumerate(secciones) if e == OBSOLETE_HEADING), None
        )
        if existente is None:
            secciones.append((OBSOLETE_HEADING, nota))
        else:
            secciones[existente][1].extend(nota)
        return _join_sections(secciones)

    raise ValidationFailedError(f"intent '{intent}' no reconocido")


def contribute(
    db: Session,
    *,
    agent_session: AgentSession,
    author_address: str,
    path: str,
    base_version: int,
    intent: str,
    anchor: str | None,
    content: str,
    rationale: str,
) -> Contribution:
    """Aplica una aportación con control de concurrencia optimista.

    El agente declara sobre qué `base_version` trabajó. Si el documento ya cambió,
    `409` con la versión vigente y su contenido: hay que releer y reconciliar, no
    reintentar con la misma base.
    """
    limpio = path.strip()
    if not limpio:
        raise ValidationFailedError("la ruta del documento no puede estar vacía")
    if not rationale.strip():
        raise ValidationFailedError(
            "el rationale es obligatorio: es lo que evita que dentro de dos "
            "semanas se renegocie esto sin saber que ya se acordó"
        )

    document = db.scalar(
        select(Document).where(
            Document.project_id == agent_session.project_id, Document.path == limpio
        )
    )

    if document is None:
        if intent != "create":
            raise NotFoundError(
                f"no existe el documento '{limpio}'; para crearlo usa intent=create "
                f"con base_version=0"
            )
        if base_version != 0:
            raise VersionConflictError(current_version=0, content="")
        document = Document(
            project_id=agent_session.project_id,
            path=limpio,
            title=_title_from(content, limpio),
        )
        db.add(document)
        db.flush()

    vigente = current_content(db, document)
    if base_version != document.current_version:
        raise VersionConflictError(current_version=document.current_version, content=vigente)

    resultante = apply_intent(
        content=vigente,
        intent=intent,
        anchor=anchor,
        aporte=content,
        author_address=author_address,
        rationale=rationale,
    )

    siguiente = base_version + 1
    if not _try_bump_version(db, document_id=document.id, base_version=base_version):
        # Comparar base_version con current_version y luego escribir es un
        # leer-luego-escribir: entre ambas cabe otra aportación. Sin este paso
        # atómico, dos agentes con la misma base pasan la comprobación y el
        # segundo choca con el constraint único de (document_id, version),
        # recibiendo un error del motor en vez del 409 documentado.
        db.expire(document)
        raise VersionConflictError(
            current_version=document.current_version,
            content=current_content(db, document),
        )

    version = DocumentVersion(
        document_id=document.id,
        version=siguiente,
        content=resultante,
        intent=intent,
        rationale=rationale.strip(),
        author_address=author_address,
        author_session_id=agent_session.id,
    )
    db.add(version)
    if not document.title:
        document.title = _title_from(resultante, limpio)
    db.flush()
    db.refresh(document)
    return Contribution(document=document, version=version)


def _try_bump_version(db: Session, *, document_id: str, base_version: int) -> bool:
    """Avanza `current_version` solo si sigue siendo `base_version`.

    Es el mismo mecanismo que el reclamo atómico de mensajes: `UPDATE ... WHERE`
    sobre el valor esperado, verificando `rowcount` dentro de la transacción.
    """
    resultado = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.current_version == base_version)
        .values(current_version=base_version + 1)
    )
    return cast("CursorResult[Any]", resultado).rowcount == 1


def _title_from(content: str, path: str) -> str:
    """Primer `#` del contenido, o la ruta si no hay ninguno."""
    for linea in content.splitlines():
        if linea.startswith("# "):
            return linea.removeprefix("# ").strip()[:300]
    return path


def count_for(db: Session, *, project_id: str) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Document).where(Document.project_id == project_id)
        )
        or 0
    )
