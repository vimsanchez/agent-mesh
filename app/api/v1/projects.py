"""Proyectos y roster.

`GET /projects` es de **solo lectura**. No hay `POST /projects` ni endpoint de
auto-membresía, ni siquiera "por conveniencia en desarrollo" (regla 9, SPEC §3.1):
si un agente pudiera crear proyectos, uno confundido levantaría un cuarto nuevo y
quedaría hablando solo creyendo que está coordinado.
"""

from fastapi import APIRouter

from app.api.v1.schemas import ProjectOut, ProjectsOut, RosterEntry, RosterOut
from app.security.deps import Config, CurrentPerson, Db
from app.services import identity, sessions

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=ProjectsOut)
def list_projects(db: Db, person: CurrentPerson) -> ProjectsOut:
    """Proyectos donde la persona del token **ya** es miembro."""
    proyectos = identity.projects_of_person(db, person)
    return ProjectsOut(
        person=person.display_name,
        projects=[
            ProjectOut(
                slug=project.slug,
                name=project.name,
                members=[p.display_name for p in identity.project_members(db, project)],
            )
            for project in proyectos
        ],
    )


@router.get("/projects/{slug}/roster", response_model=RosterOut)
def roster(db: Db, person: CurrentPerson, settings: Config, slug: str) -> RosterOut:
    """Quién está vivo ahora mismo en el proyecto."""
    filas = sessions.roster(db, settings, person=person, slug=slug)
    db.commit()
    return RosterOut(
        sessions=[
            RosterEntry(
                address=address,
                status=agent_session.status,
                last_seen_at=agent_session.last_seen_at,
            )
            for agent_session, address in filas
        ]
    )
