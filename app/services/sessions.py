"""Sesiones de agente: registro, latido, cierre y quién está vivo.

Sobre el marcado de `stale`: **es perezoso, no hay tarea de fondo.** El stack no
tiene planificador y meter uno para esto sería peso extra en un servicio que
mueve unos mensajes por hora. En su lugar, `expire_stale_sessions` se llama al
leer roster, inbox y no reclamados, y materializa el cambio en esa misma
transacción.

La consecuencia a tener presente: una sesión muerta sigue apareciendo `active`
hasta que alguien mira. Da igual, porque el único efecto de estar `stale` es que
sus mensajes vuelvan a circular, y eso solo importa cuando alguien va a leerlos.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import utcnow
from app.db.ids import new_session_key
from app.db.models import AgentSession, Person, Project, ProjectMember
from app.services import addressing
from app.services.errors import (
    ForbiddenError,
    NotFoundError,
    SessionGoneError,
)

LIVE_STATUSES = ("active",)


# ------------------------------------------------------------------- pertenencia


def assert_member(db: Session, *, person: Person, slug: str) -> Project:
    """Resuelve el proyecto comprobando que la persona pertenece.

    Es la compuerta del aislamiento (regla 2): toda lectura de datos de un
    proyecto pasa por aquí. Si esto no se llama, se filtra.

    Distingue 404 (el proyecto no existe) de 403 (existe pero no eres miembro).
    Sí, eso revela si un slug existe — y es deliberado: SPEC §11 lo pide
    explícitamente, porque un agente que recibe "no autorizado" ante un slug mal
    escrito se pone a probar variantes, que es justo el comportamiento que hay
    que evitar.
    """
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise NotFoundError(
            f"no existe el proyecto '{slug}'; revisa la lista con el comando "
            f"projects y detente si no aparece"
        )
    if not project.is_active:
        raise ForbiddenError(f"el proyecto '{slug}' está desactivado; avísale a tu persona")
    member = db.get(ProjectMember, (project.id, person.id))
    if member is None:
        raise ForbiddenError(
            f"tu persona no es miembro de '{slug}'; pídele a tu administrador "
            f"que la agregue a este proyecto. No pruebes otros slugs."
        )
    return project


# ----------------------------------------------------------------------- stale


def expire_stale_sessions(
    db: Session, settings: Settings, *, project_id: str | None = None
) -> list[AgentSession]:
    """Pasa a `stale` las sesiones sin latido y devuelve las que acaba de marcar.

    Devolver la lista es lo que permite que la mensajería (paso 5) haga volver a
    circular los mensajes que esas sesiones tenían sin confirmar, sin que este
    módulo sepa nada de mensajes.
    """
    cutoff = utcnow() - timedelta(seconds=settings.session_stale_after_seconds)
    query = select(AgentSession).where(
        AgentSession.status == "active",
        AgentSession.last_seen_at < cutoff,
    )
    if project_id is not None:
        query = query.where(AgentSession.project_id == project_id)

    caidas = list(db.scalars(query))
    for agent_session in caidas:
        agent_session.status = "stale"
    if caidas:
        db.flush()
    return caidas


# -------------------------------------------------------------------- registro


def register(db: Session, *, person: Person, slug: str, role_label: str) -> AgentSession:
    """Registra una sesión. El rol es una etiqueta libre, no un catálogo.

    **No se rechaza un rol repetido.** Si la misma persona ya tiene una sesión
    viva con ese rol, se crea otra: SPEC §3 dice que en ese caso el mensaje se
    ofrece a ambas y decide el reclamo atómico.
    """
    project = assert_member(db, person=person, slug=slug)
    role = role_label.strip().lower()
    if not role:
        raise ForbiddenError("el rol no puede estar vacío; usa 'general' si haces de todo")

    agent_session = AgentSession(
        project_id=project.id,
        person_id=person.id,
        role_label=role,
        session_key=new_session_key(),
    )
    db.add(agent_session)
    db.flush()
    return agent_session


def address_of(db: Session, agent_session: AgentSession) -> str:
    person = db.get(Person, agent_session.person_id)
    if person is None:  # pragma: no cover - lo impide la FK
        raise NotFoundError("la persona de esta sesión ya no existe")
    return addressing.format_address(person.display_name, agent_session.role_label)


# --------------------------------------------------------------- ciclo de vida


def by_key(db: Session, *, person: Person, session_key: str) -> AgentSession:
    """Busca una sesión exigiendo que sea de esta persona.

    Sin esa comprobación, quien tuviera un `session_key` ajeno podría mantener
    viva o cerrar la sesión de otro.
    """
    agent_session = db.scalar(
        select(AgentSession).where(AgentSession.session_key == session_key)
    )
    if agent_session is None or agent_session.person_id != person.id:
        raise NotFoundError("no existe esa sesión")
    return agent_session


def heartbeat(
    db: Session, *, person: Person, session_key: str, settings: Settings
) -> AgentSession:
    """Mantiene la sesión `active`.

    Una sesión ya `stale` **no revive**: devuelve 410 y el agente vuelve a
    registrarse, como indica la tabla de errores de `api.md`. Revivirla dejaría
    en el aire los mensajes que ya volvieron a circular por su ausencia.
    """
    agent_session = by_key(db, person=person, session_key=session_key)
    if agent_session.status != "active":
        raise SessionGoneError
    agent_session.last_seen_at = utcnow()
    db.flush()
    return agent_session


def close(db: Session, *, person: Person, session_key: str) -> AgentSession:
    """Cierre limpio. Idempotente: cerrar dos veces no es error."""
    agent_session = by_key(db, person=person, session_key=session_key)
    if agent_session.status != "closed":
        agent_session.status = "closed"
        db.flush()
    return agent_session


def roster(
    db: Session, settings: Settings, *, person: Person, slug: str
) -> list[tuple[AgentSession, str]]:
    """Sesiones vivas del proyecto, con su dirección.

    Marca las caídas antes de responder: si no, el roster diría que sigue vivo
    alguien que lleva media hora sin latir.
    """
    project = assert_member(db, person=person, slug=slug)
    expire_stale_sessions(db, settings, project_id=project.id)

    filas = db.execute(
        select(AgentSession, Person)
        .join(Person, Person.id == AgentSession.person_id)
        .where(
            AgentSession.project_id == project.id,
            AgentSession.status.in_(LIVE_STATUSES),
        )
        .order_by(Person.display_name, AgentSession.role_label)
    ).all()
    return [
        (agent_session, addressing.format_address(p.display_name, agent_session.role_label))
        for agent_session, p in filas
    ]
