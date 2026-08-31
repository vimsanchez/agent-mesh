"""Rutas del panel. Server-rendered con Jinja2, sin framework de frontend.

Los handlers solo validan la forma, llaman a `services.identity` y renderizan.
Ninguna regla de negocio vive aquí.

**La cookie de sesión va firmada pero NO cifrada**: quien tenga el navegador
puede leer su contenido. Por eso solo guarda el id del administrador y mensajes
de una sola pasada. Nunca un token, nunca una contraseña.
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.admin.deps import (
    SESSION_ADMIN_KEY,
    ActiveAdmin,
    CurrentAdmin,
    Db,
    redirect,
)
from app.config import get_settings
from app.db.models import (
    AccessToken,
    AdminUser,
    AgentSession,
    Document,
    Message,
    Person,
    Project,
    Thread,
)
from app.services import export, identity, knowledge, timefmt
from app.services.errors import DomainError

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _hora(momento: datetime, segundos: bool = False) -> str:
    """Filtro `hora` de las plantillas: UTC de la base -> zona del panel.

    La zona se resuelve en cada render y no al importar, para que un cambio de
    `DISPLAY_TIMEZONE` surta efecto reiniciando y no reconstruyendo.
    """
    return timefmt.stamp(
        momento, timefmt.zona(get_settings().display_timezone), segundos=segundos
    )


def _fecha(momento: datetime) -> str:
    """Filtro `fecha`: solo el día, ya convertido a la zona del panel."""
    return timefmt.day(momento, timefmt.zona(get_settings().display_timezone))


templates.env.filters["hora"] = _hora
templates.env.filters["fecha"] = _fecha

_FLASH_ERROR = "flash_error"
_FLASH_NOTICE = "flash_notice"


# ------------------------------------------------------------------- utilidades


def flash(request: Request, message: str, *, error: bool = False) -> None:
    """Mensaje de una sola pasada, para sobrevivir al redirect tras un POST."""
    request.session[_FLASH_ERROR if error else _FLASH_NOTICE] = message


def render(
    request: Request,
    template: str,
    admin: AdminUser | None = None,
    **context: Any,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "admin": admin,
            "error": request.session.pop(_FLASH_ERROR, None),
            "notice": request.session.pop(_FLASH_NOTICE, None),
            **context,
        },
    )


# ------------------------------------------------------------------ autenticación


@router.get("/login", response_model=None, include_in_schema=False)
def login_form(request: Request) -> HTMLResponse:
    return render(request, "login.html")


@router.post("/login", response_model=None, include_in_schema=False)
def login(
    request: Request,
    db: Db,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse:
    admin = identity.authenticate_admin(db, email=email, password=password)
    if admin is None:
        # Un solo mensaje para "no existe" y "contraseña mala": distinguirlos
        # convertiría el login en un oráculo de qué correos están dados de alta.
        flash(request, "Correo o contraseña incorrectos.", error=True)
        return redirect("/admin/login")

    db.commit()
    request.session[SESSION_ADMIN_KEY] = admin.id
    if admin.must_change_password:
        return redirect("/admin/password")
    return redirect("/admin")


@router.get("/logout", response_model=None, include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return redirect("/admin/login")


@router.get("/password", response_model=None, include_in_schema=False)
def password_form(request: Request, admin: CurrentAdmin) -> HTMLResponse:
    return render(request, "password.html", admin=admin)


@router.post("/password", response_model=None, include_in_schema=False)
def change_password(
    request: Request,
    db: Db,
    admin: CurrentAdmin,
    password: Annotated[str, Form()],
    repeat: Annotated[str, Form()],
) -> RedirectResponse:
    if password != repeat:
        flash(request, "Las dos contraseñas no coinciden.", error=True)
        return redirect("/admin/password")
    try:
        identity.change_admin_password(db, admin, password)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/password")

    db.commit()
    flash(request, "Contraseña actualizada.")
    return redirect("/admin")


# ------------------------------------------------------------------------ resumen


@router.get("", response_model=None, include_in_schema=False)
def index(request: Request, db: Db, admin: ActiveAdmin) -> HTMLResponse:
    counts = {
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "people": db.scalar(select(func.count()).select_from(Person)) or 0,
        "tokens": db.scalar(
            select(func.count())
            .select_from(AccessToken)
            .where(AccessToken.revoked_at.is_(None))
        )
        or 0,
        "sessions": db.scalar(
            select(func.count())
            .select_from(AgentSession)
            .where(AgentSession.status == "active")
        )
        or 0,
    }
    sessions = list(
        db.execute(
            select(AgentSession, Project, Person)
            .join(Project, Project.id == AgentSession.project_id)
            .join(Person, Person.id == AgentSession.person_id)
            .order_by(AgentSession.last_seen_at.desc())
            .limit(50)
        ).all()
    )
    return render(request, "index.html", admin=admin, counts=counts, sessions=sessions)


# --------------------------------------------------------------------- proyectos


@router.get("/projects", response_model=None, include_in_schema=False)
def projects_page(request: Request, db: Db, admin: ActiveAdmin) -> HTMLResponse:
    projects = [
        (project, identity.project_members(db, project))
        for project in identity.list_projects(db)
    ]
    return render(request, "projects.html", admin=admin, projects=projects)


@router.post("/projects", response_model=None, include_in_schema=False)
def create_project(
    request: Request,
    db: Db,
    admin: ActiveAdmin,
    slug: Annotated[str, Form()],
    name: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        project = identity.create_project(db, slug=slug, name=name)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    db.commit()
    flash(request, f"Proyecto '{project.slug}' creado.")
    return redirect(f"/admin/projects/{project.slug}")


@router.get("/projects/{slug}", response_model=None, include_in_schema=False)
def project_detail(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> HTMLResponse | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    members = identity.project_members(db, project)
    member_ids = {person.id for person in members}
    candidates = [p for p in identity.list_people(db) if p.id not in member_ids]
    return render(
        request,
        "project_detail.html",
        admin=admin,
        project=project,
        members=members,
        candidates=candidates,
    )


@router.post("/projects/{slug}/members", response_model=None, include_in_schema=False)
def add_member(
    request: Request,
    db: Db,
    admin: ActiveAdmin,
    slug: str,
    person_id: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
        person = identity.get_person(db, person_id)
        identity.add_member(db, project=project, person=person)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect(f"/admin/projects/{slug}")

    db.commit()
    flash(request, f"'{person.display_name}' agregada a '{slug}'.")
    return redirect(f"/admin/projects/{slug}")


@router.post(
    "/projects/{slug}/members/{person_id}/remove", response_model=None, include_in_schema=False
)
def remove_member(
    request: Request, db: Db, admin: ActiveAdmin, slug: str, person_id: str
) -> RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
        person = identity.get_person(db, person_id)
        identity.remove_member(db, project=project, person=person)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect(f"/admin/projects/{slug}")

    db.commit()
    flash(request, f"'{person.display_name}' ya no es miembro de '{slug}'.")
    return redirect(f"/admin/projects/{slug}")


# ------------------------------------------- vistas de solo lectura (SPEC §10.8)
#
# El panel NO envía mensajes, no reclama, no aporta y no cambia estados. Es una
# ventana para que una persona entienda qué están haciendo los agentes. Toda
# escritura de coordinación pasa por la API, que es donde vive el aislamiento y
# donde el reclamo es atómico.


@router.get("/projects/{slug}/threads", response_model=None, include_in_schema=False)
def project_threads(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> HTMLResponse | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    filas = db.execute(
        select(Thread, func.count(Message.id))
        .outerjoin(Message, Message.thread_id == Thread.id)
        .where(Thread.project_id == project.id)
        .group_by(Thread.id)
        .order_by(Thread.updated_at.desc())
    ).all()
    return render(request, "threads.html", admin=admin, project=project, threads=filas)


@router.get(
    "/projects/{slug}/threads/{thread_id}",
    response_model=None,
    include_in_schema=False,
)
def project_thread_detail(
    request: Request, db: Db, admin: ActiveAdmin, slug: str, thread_id: str
) -> HTMLResponse | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    thread = db.get(Thread, thread_id)
    # La comprobación de proyecto también aquí: el panel no es una puerta trasera
    # al aislamiento solo porque quien mira sea administrador.
    if thread is None or thread.project_id != project.id:
        flash(request, f"no existe ese hilo en '{slug}'", error=True)
        return redirect(f"/admin/projects/{slug}/threads")

    mensajes = list(
        db.scalars(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    return render(
        request,
        "thread_detail.html",
        admin=admin,
        project=project,
        thread=thread,
        messages=mensajes,
    )


@router.get("/projects/{slug}/docs", response_model=None, include_in_schema=False)
def project_docs(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> HTMLResponse | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    return render(
        request,
        "documents.html",
        admin=admin,
        project=project,
        documents=knowledge.index(db, project_id=project.id),
    )


@router.get("/projects/{slug}/docs/{document_id}", response_model=None, include_in_schema=False)
def project_doc_detail(
    request: Request, db: Db, admin: ActiveAdmin, slug: str, document_id: str
) -> HTMLResponse | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    document = db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        flash(request, f"no existe ese documento en '{slug}'", error=True)
        return redirect(f"/admin/projects/{slug}/docs")

    return render(
        request,
        "document_detail.html",
        admin=admin,
        project=project,
        document=document,
        content=knowledge.current_content(db, document),
        versions=knowledge.history_of(db, document),
    )


# ------------------------------------------------- exportar a Markdown (panel)
#
# Lectura pura, igual que las vistas de arriba: no marca ni registra nada. La
# frontera de proyecto se resuelve aquí, como en el resto del panel; el servicio
# `export` solo serializa lo que se le entrega.


def _attachment(content: bytes | str, *, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _markdown(content: str, *, filename: str) -> Response:
    return _attachment(content, filename=filename, media_type="text/markdown; charset=utf-8")


def _zip(content: bytes, *, filename: str) -> Response:
    return _attachment(content, filename=filename, media_type="application/zip")


@router.get(
    "/projects/{slug}/threads/{thread_id}/download",
    response_model=None,
    include_in_schema=False,
)
def download_thread(
    request: Request, db: Db, admin: ActiveAdmin, slug: str, thread_id: str
) -> Response | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    thread = db.get(Thread, thread_id)
    if thread is None or thread.project_id != project.id:
        flash(request, f"no existe ese hilo en '{slug}'", error=True)
        return redirect(f"/admin/projects/{slug}/threads")

    return _markdown(
        export.thread_markdown(project, thread, export.messages_of(db, thread)),
        filename=export.thread_filename(thread),
    )


@router.get(
    "/projects/{slug}/docs/{document_id}/download",
    response_model=None,
    include_in_schema=False,
)
def download_document(
    request: Request, db: Db, admin: ActiveAdmin, slug: str, document_id: str
) -> Response | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    document = db.get(Document, document_id)
    if document is None or document.project_id != project.id:
        flash(request, f"no existe ese documento en '{slug}'", error=True)
        return redirect(f"/admin/projects/{slug}/docs")

    return _markdown(
        export.document_markdown(knowledge.current_content(db, document)),
        filename=export.document_filename(document.path),
    )


@router.get("/projects/{slug}/threads.zip", response_model=None, include_in_schema=False)
def download_threads(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> Response | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    contenido = export.project_zip(
        project, threads=export.threads_of(db, project), documents=None
    )
    return _zip(contenido, filename=f"{project.slug}-hilos.zip")


@router.get("/projects/{slug}/docs.zip", response_model=None, include_in_schema=False)
def download_documents(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> Response | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    contenido = export.project_zip(
        project, threads=None, documents=export.documents_of(db, project)
    )
    return _zip(contenido, filename=f"{project.slug}-docs.zip")


@router.get("/projects/{slug}/export.zip", response_model=None, include_in_schema=False)
def download_project(
    request: Request, db: Db, admin: ActiveAdmin, slug: str
) -> Response | RedirectResponse:
    try:
        project = identity.get_project_by_slug(db, slug)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/projects")

    contenido = export.project_zip(
        project,
        threads=export.threads_of(db, project),
        documents=export.documents_of(db, project),
    )
    return _zip(contenido, filename=f"{project.slug}.zip")


# ---------------------------------------------------------------------- personas


@router.get("/people", response_model=None, include_in_schema=False)
def people_page(request: Request, db: Db, admin: ActiveAdmin) -> HTMLResponse:
    people = [
        (
            person,
            identity.projects_of_person(db, person),
            sum(1 for t in identity.tokens_of_person(db, person) if t.revoked_at is None),
        )
        for person in identity.list_people(db)
    ]
    return render(request, "people.html", admin=admin, people=people)


@router.post("/people", response_model=None, include_in_schema=False)
def create_person(
    request: Request,
    db: Db,
    admin: ActiveAdmin,
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
) -> RedirectResponse:
    try:
        person = identity.create_person(db, email=email, display_name=display_name)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/people")

    db.commit()
    flash(request, f"Persona '{person.display_name}' dada de alta.")
    return redirect(f"/admin/people/{person.id}")


def _person_page(
    request: Request, db: Db, admin: AdminUser, person: Person, new_token: str | None = None
) -> HTMLResponse:
    return render(
        request,
        "person_detail.html",
        admin=admin,
        person=person,
        projects=identity.projects_of_person(db, person),
        tokens=identity.tokens_of_person(db, person),
        new_token=new_token,
    )


@router.get("/people/{person_id}", response_model=None, include_in_schema=False)
def person_detail(
    request: Request, db: Db, admin: ActiveAdmin, person_id: str
) -> HTMLResponse | RedirectResponse:
    try:
        person = identity.get_person(db, person_id)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/people")
    return _person_page(request, db, admin, person)


@router.post("/people/{person_id}/tokens", response_model=None, include_in_schema=False)
def issue_token(
    request: Request,
    db: Db,
    admin: ActiveAdmin,
    person_id: str,
    label: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    """Emite y **renderiza directamente**, sin redirect.

    Es a propósito: el token en claro se ve una sola vez y no puede viajar por la
    sesión, porque la cookie va firmada pero no cifrada y quedaría legible en el
    navegador. El precio es que recargar la página reemitiría otro token, lo cual
    es inocuo: se revoca y ya.
    """
    try:
        person = identity.get_person(db, person_id)
        issued = identity.issue_token(db, person=person, label=label)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect("/admin/people")

    db.commit()
    return _person_page(request, db, admin, person, new_token=issued.plain)


@router.post(
    "/people/{person_id}/tokens/{token_id}/revoke", response_model=None, include_in_schema=False
)
def revoke_token(
    request: Request, db: Db, admin: ActiveAdmin, person_id: str, token_id: str
) -> RedirectResponse:
    try:
        identity.revoke_token(db, token_id)
    except DomainError as exc:
        flash(request, exc.detail, error=True)
        return redirect(f"/admin/people/{person_id}")

    db.commit()
    flash(request, "Token revocado. Los agentes que lo usen recibirán 401.")
    return redirect(f"/admin/people/{person_id}")
