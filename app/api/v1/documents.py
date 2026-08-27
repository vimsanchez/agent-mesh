"""Documentos: índice, lectura, aportaciones e historial.

El índice va por slug de proyecto (`api.md`) mientras la lectura y la aportación
resuelven el proyecto desde la sesión. Esa asimetría es la del contrato, no una
decisión nuestra; lo importante es que **las tres vías validan pertenencia**,
porque son el camino más fácil de fugar datos entre proyectos.
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.v1.schemas import (
    ContributeIn,
    DocumentIndexEntry,
    DocumentIndexOut,
    DocumentOut,
    VersionEntry,
    VersionsOut,
)
from app.security.deps import CurrentPerson, CurrentSession, Db
from app.services import knowledge, sessions
from app.services.knowledge import VersionConflictError

router = APIRouter(tags=["documents"])


@router.get("/projects/{slug}/docs", response_model=DocumentIndexOut)
def index(db: Db, person: CurrentPerson, slug: str) -> DocumentIndexOut:
    """Índice del proyecto. Solo para quien es miembro."""
    project = sessions.assert_member(db, person=person, slug=slug)
    return DocumentIndexOut(
        documents=[
            DocumentIndexEntry(
                id=document.id,
                path=document.path,
                title=document.title,
                current_version=document.current_version,
                updated_at=document.updated_at,
            )
            for document in knowledge.index(db, project_id=project.id)
        ]
    )


@router.get("/docs", response_model=DocumentOut)
def read(db: Db, agent_session: CurrentSession, path: str = Query(...)) -> DocumentOut:
    """Documento con su contenido y `current_version`."""
    document = knowledge.by_path(db, project_id=agent_session.project_id, path=path)
    return DocumentOut(
        id=document.id,
        path=document.path,
        title=document.title,
        current_version=document.current_version,
        content=knowledge.current_content(db, document),
        status=document.status,
        updated_at=document.updated_at,
    )


@router.post("/docs/contributions", response_model=DocumentOut)
def contribute(
    db: Db, agent_session: CurrentSession, body: ContributeIn
) -> DocumentOut | JSONResponse:
    """Aporta a un documento. `409` si `base_version` no es la vigente.

    El 409 se construye a mano porque debe llevar `current_version` y el contenido
    vigente además del `detail`: sin eso el agente solo puede reintentar a ciegas,
    y `api.md` promete ambos.
    """
    # El autor se congela como buzón del rol (`victor.db`), no como dirección
    # precisa: el historial debe seguir siendo legible cuando esa sesión ya no
    # exista, y el sufijo caduca con ella.
    author = sessions.address_of(db, agent_session)
    try:
        aportacion = knowledge.contribute(
            db,
            agent_session=agent_session,
            author_address=author,
            path=body.document_path,
            base_version=body.base_version,
            intent=body.intent,
            anchor=body.anchor,
            content=body.content,
            rationale=body.rationale,
        )
    except VersionConflictError as conflicto:
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={
                "detail": conflicto.detail,
                "current_version": conflicto.current_version,
                "content": conflicto.content,
            },
        )

    salida = DocumentOut(
        id=aportacion.document.id,
        path=aportacion.document.path,
        title=aportacion.document.title,
        current_version=aportacion.document.current_version,
        content=aportacion.version.content,
        status=aportacion.document.status,
        updated_at=aportacion.document.updated_at,
    )
    db.commit()
    return salida


@router.get("/docs/{document_id}/versions", response_model=VersionsOut)
def versions(db: Db, agent_session: CurrentSession, document_id: str) -> VersionsOut:
    """Historial: versión, autor (`persona.rol`), intención, motivo y fecha."""
    document, historial = knowledge.history(
        db, agent_session=agent_session, document_id=document_id
    )
    return VersionsOut(
        document_id=document.id,
        path=document.path,
        versions=[
            VersionEntry(
                version=v.version,
                intent=v.intent,
                rationale=v.rationale,
                author_address=v.author_address,
                created_at=v.created_at,
            )
            for v in historial
        ],
    )
