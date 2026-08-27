"""Identidad: administradores, personas, proyectos, membresías y tokens.

Toda la lógica vive aquí; los handlers solo validan, llaman y serializan
(CLAUDE.md, "Convenciones de código").

Nota importante sobre alcance: **crear proyectos y asignar membresías solo se
llama desde el panel.** La API de agentes no expone ninguna de estas funciones
(regla 9, SPEC §3.1). Si un agente pudiera crear proyectos, uno confundido
levantaría un cuarto nuevo y quedaría hablando solo creyendo que está coordinado
— un fallo silencioso, la peor clase.
"""

import re
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import utcnow
from app.db.models import AccessToken, AdminUser, Person, Project, ProjectMember
from app.security import passwords, tokens
from app.services.errors import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


# ------------------------------------------------------------------ validación


def email_domain(email: str) -> str:
    _, _, domain = email.partition("@")
    return domain.lower()


def assert_admin_domain(email: str, settings: Settings) -> None:
    """El correo de un administrador debe pertenecer a `ADMIN_EMAIL_DOMAIN`.

    Se compara contra `admin_email_domain` y **nunca** contra
    `public_service_domain`: son variables sin relación (regla 6). Mezclarlas
    aquí dejaría entrar al panel a cualquiera con correo del dominio público.
    """
    domain = email_domain(email)
    if not domain:
        raise ValidationFailedError(f"'{email}' no es un correo")
    if domain != settings.admin_email_domain.lower():
        raise ValidationFailedError(
            f"solo se admiten correos de '{settings.admin_email_domain}'; "
            f"'{email}' es de '{domain}'"
        )


# ----------------------------------------------------------- administradores


def create_admin(
    db: Session,
    *,
    email: str,
    password: str,
    settings: Settings,
    role: str = "admin",
    must_change_password: bool = False,
) -> AdminUser:
    assert_admin_domain(email, settings)
    if db.scalar(select(AdminUser).where(AdminUser.email == email.lower())):
        raise ConflictError(f"ya existe un administrador con el correo '{email}'")

    admin = AdminUser(
        email=email.lower(),
        password_hash=passwords.hash_password(password),
        role=role,
        must_change_password=must_change_password,
    )
    db.add(admin)
    db.flush()
    return admin


def authenticate_admin(db: Session, *, email: str, password: str) -> AdminUser | None:
    """`None` ante cualquier fallo, sin distinguir el motivo.

    No se dice "ese correo no existe" ni "la contraseña es incorrecta": eso
    convertiría el login en un oráculo de qué correos están dados de alta.
    """
    admin = db.scalar(select(AdminUser).where(AdminUser.email == email.lower()))
    if admin is None or not admin.is_active:
        return None
    if not passwords.verify_password(password, admin.password_hash):
        return None

    admin.last_login_at = utcnow()
    if passwords.needs_rehash(admin.password_hash):
        admin.password_hash = passwords.hash_password(password)
    db.flush()
    return admin


def change_admin_password(db: Session, admin: AdminUser, new_password: str) -> None:
    if len(new_password) < 12:
        raise ValidationFailedError("la contraseña debe tener al menos 12 caracteres")
    admin.password_hash = passwords.hash_password(new_password)
    admin.must_change_password = False
    db.flush()


def bootstrap_admin(db: Session, settings: Settings) -> tuple[AdminUser, str] | None:
    """Crea el administrador inicial al primer arranque (SPEC §9).

    Devuelve `None` si ya hay administradores: es idempotente, así que reiniciar
    el contenedor no genera credenciales nuevas ni pisa las existentes.

    La contraseña se devuelve en claro **una sola vez** para que quien llama la
    imprima en el log de arranque, y la cuenta queda con
    `must_change_password=True`.
    """
    if db.scalar(select(func.count()).select_from(AdminUser)):
        return None

    password = secrets.token_urlsafe(18)
    admin = create_admin(
        db,
        email=settings.bootstrap_admin_email,
        password=password,
        settings=settings,
        role="owner",
        must_change_password=True,
    )
    return admin, password


# ------------------------------------------------------------------- personas


def create_person(db: Session, *, email: str, display_name: str) -> Person:
    """Una persona no entra a ningún lado: es a quien representa un token.

    `display_name` es el primer componente de la dirección pública
    `persona.rol`, así que se restringe a algo que quepa en una dirección sin
    ambigüedad. Un punto de más aquí rompería el parseo de `victor.db`.
    """
    name = display_name.strip().lower()
    if not NAME_PATTERN.match(name) or "." in name:
        raise ValidationFailedError(
            f"'{display_name}' no sirve como nombre: usa minúsculas, números, "
            f"guiones o guiones bajos, y sin puntos (el punto separa persona de rol)"
        )
    if db.scalar(select(Person).where(Person.display_name == name)):
        raise ConflictError(f"ya existe una persona con el nombre '{name}'")
    if db.scalar(select(Person).where(Person.email == email.lower())):
        raise ConflictError(f"ya existe una persona con el correo '{email}'")

    person = Person(email=email.lower(), display_name=name)
    db.add(person)
    db.flush()
    return person


def get_person(db: Session, person_id: str) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise NotFoundError(f"no existe la persona '{person_id}'")
    return person


def list_people(db: Session) -> list[Person]:
    return list(db.scalars(select(Person).order_by(Person.display_name)))


# ------------------------------------------------------------------ proyectos


def create_project(db: Session, *, slug: str, name: str, description: str = "") -> Project:
    """Solo desde el panel. Ver la nota de alcance al principio del módulo."""
    clean = slug.strip().lower()
    if not SLUG_PATTERN.match(clean):
        raise ValidationFailedError(
            f"'{slug}' no sirve como slug: usa minúsculas, números y guiones "
            f"(por ejemplo 'proyecto-pablo')"
        )
    if db.scalar(select(Project).where(Project.slug == clean)):
        raise ConflictError(f"ya existe un proyecto con el slug '{clean}'")

    project = Project(slug=clean, name=name.strip(), description=description.strip())
    db.add(project)
    db.flush()
    return project


def get_project_by_slug(db: Session, slug: str) -> Project:
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise NotFoundError(f"no existe el proyecto '{slug}'")
    return project


def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.slug)))


def add_member(db: Session, *, project: Project, person: Person) -> ProjectMember:
    existing = db.get(ProjectMember, (project.id, person.id))
    if existing is not None:
        raise ConflictError(f"'{person.display_name}' ya es miembro de '{project.slug}'")
    member = ProjectMember(project_id=project.id, person_id=person.id)
    db.add(member)
    db.flush()
    return member


def remove_member(db: Session, *, project: Project, person: Person) -> None:
    member = db.get(ProjectMember, (project.id, person.id))
    if member is None:
        raise NotFoundError(f"'{person.display_name}' no es miembro de '{project.slug}'")
    db.delete(member)
    db.flush()


def project_members(db: Session, project: Project) -> list[Person]:
    return list(
        db.scalars(
            select(Person)
            .join(ProjectMember, ProjectMember.person_id == Person.id)
            .where(ProjectMember.project_id == project.id)
            .order_by(Person.display_name)
        )
    )


def projects_of_person(db: Session, person: Person) -> list[Project]:
    """Base de `GET /projects` (SPEC §3.2). Solo lectura, nunca crea nada."""
    return list(
        db.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.person_id == person.id, Project.is_active.is_(True))
            .order_by(Project.slug)
        )
    )


# --------------------------------------------------------------------- tokens


@dataclass(frozen=True)
class IssuedToken:
    """El token en claro solo existe en este objeto, de vuelta al panel.

    Nunca se persiste así ni se vuelve a poder consultar.
    """

    record: AccessToken
    plain: str


def issue_token(db: Session, *, person: Person, label: str = "") -> IssuedToken:
    plain = tokens.new_token()
    record = AccessToken(
        person_id=person.id,
        token_hash=tokens.hash_token(plain),
        label=label.strip(),
    )
    db.add(record)
    db.flush()
    return IssuedToken(record=record, plain=plain)


def revoke_token(db: Session, token_id: str) -> AccessToken:
    """Revocar no borra: se conserva el rastro de qué token existió y cuándo murió."""
    record = db.get(AccessToken, token_id)
    if record is None:
        raise NotFoundError(f"no existe el token '{token_id}'")
    if record.revoked_at is None:
        record.revoked_at = utcnow()
        db.flush()
    return record


def tokens_of_person(db: Session, person: Person) -> list[AccessToken]:
    return list(
        db.scalars(
            select(AccessToken)
            .where(AccessToken.person_id == person.id)
            .order_by(AccessToken.created_at.desc())
        )
    )


def resolve_token(db: Session, plain: str) -> Person:
    """Traduce un token en claro a la persona que representa.

    Es el camino caliente: se ejecuta en cada petición de la API de agentes. Un
    solo lookup por índice único, sin hash lento (ver `security/tokens.py`).

    Lanza `UnauthorizedError` tanto si el token no existe como si está revocado,
    con el mismo mensaje: distinguirlos le diría a quien prueba tokens cuáles
    existieron alguna vez.
    """
    if not tokens.looks_like_token(plain):
        raise UnauthorizedError("token inválido o revocado; detente y avísale a tu persona")

    record = db.scalar(
        select(AccessToken).where(AccessToken.token_hash == tokens.hash_token(plain))
    )
    if record is None or record.revoked_at is not None:
        raise UnauthorizedError("token inválido o revocado; detente y avísale a tu persona")

    person = db.get(Person, record.person_id)
    if person is None or not person.is_active:
        raise UnauthorizedError("token inválido o revocado; detente y avísale a tu persona")

    record.last_used_at = utcnow()
    return person
