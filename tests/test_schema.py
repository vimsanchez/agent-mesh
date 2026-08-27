"""M2: el esquema completo de SPEC §7 existe y sostiene sus invariantes.

Regla 8 de CLAUDE.md: las 12 tablas existen desde el primer commit aunque varias
no se usen todavía. Estas pruebas verifican tanto la forma como las garantías
que el esquema debe dar por sí solo, sin ayuda del código de aplicación.
"""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import enums
from app.db.base import Base
from app.db.models import Document, DocumentVersion, Message
from tests import factories as f
from tests.conftest import alembic_config

TABLAS_SPEC_7 = {
    "admin_users",
    "people",
    "access_tokens",
    "projects",
    "project_members",
    "sessions",
    "threads",
    "messages",
    "message_deliveries",
    "message_dismissals",
    "documents",
    "document_versions",
}


# ------------------------------------------------------------------- estructura


def test_estan_las_doce_tablas(migrated_engine: Engine) -> None:
    presentes = set(inspect(migrated_engine).get_table_names())

    assert presentes >= TABLAS_SPEC_7, TABLAS_SPEC_7 - presentes


def test_estan_los_indices_minimos_de_spec_7(migrated_engine: Engine) -> None:
    """Los cuatro que el spec nombra explícitamente."""
    inspector = inspect(migrated_engine)

    def columnas_indexadas(tabla: str) -> set[tuple[str, ...]]:
        return {
            tuple(index["column_names"])  # type: ignore[arg-type]
            for index in inspector.get_indexes(tabla)
        }

    assert ("project_id", "recipient_address", "status") in columnas_indexadas("messages")
    assert ("project_id", "status") in columnas_indexadas("messages")
    assert ("project_id", "person_id", "role_label") in columnas_indexadas("sessions")

    unicos = {tuple(c["column_names"]) for c in inspector.get_unique_constraints("documents")}
    assert ("project_id", "path") in unicos


def test_la_migracion_no_ha_divergido_de_los_modelos(migrated_engine: Engine) -> None:
    """Red de seguridad: si alguien toca un modelo y olvida la migración, esto falla.

    Es la prueba que evita que el esquema del contenedor y el de los modelos se
    separen en silencio durante los pasos siguientes.
    """
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diferencias = compare_metadata(context, Base.metadata)

    assert diferencias == [], f"la migración quedó desfasada: {diferencias}"


def test_upgrade_y_downgrade_completo(tmp_db_url: str) -> None:
    config = alembic_config(tmp_db_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")


# ---------------------------------------------------------------- enumeraciones


def test_message_status_tiene_los_cinco_estados_de_spec_5_2() -> None:
    """Ni uno más. `ack` no es un estado: vive en message_deliveries.acked_at."""
    assert enums.MESSAGE_STATUSES == (
        "pending",
        "delivered",
        "in_progress",
        "answered",
        "unclaimed",
    )
    assert "acked" not in enums.MESSAGE_STATUSES


@pytest.mark.parametrize("valor_invalido", ["acked", "ANSWERED", "", "resuelto"])
def test_un_status_fuera_del_enum_es_rechazado(db: Session, valor_invalido: str) -> None:
    project = f.make_project(db)
    thread = f.make_thread(db, project)

    # `make_message` ya hace flush, así que el constraint salta ahí mismo.
    with pytest.raises(IntegrityError):
        f.make_message(db, project, thread, status=valor_invalido)


def test_un_kind_fuera_del_enum_es_rechazado(db: Session) -> None:
    project = f.make_project(db)
    thread = f.make_thread(db, project)

    with pytest.raises(IntegrityError):
        f.make_message(db, project, thread, kind="chisme")


def test_los_cinco_kinds_validos_pasan(db: Session) -> None:
    project = f.make_project(db)
    thread = f.make_thread(db, project)

    for kind in enums.MESSAGE_KINDS:
        f.make_message(db, project, thread, kind=kind)

    db.flush()


# -------------------------------------------------------------------- garantías


def test_un_mensaje_puede_no_tener_destinatario(db: Session) -> None:
    """`to` nulo -> nace en la bandeja de no reclamados (SPEC §5.1)."""
    project = f.make_project(db)
    thread = f.make_thread(db, project)

    mensaje = f.make_message(db, project, thread, recipient=None)

    assert mensaje.recipient_address is None


def test_se_puede_escribir_a_un_rol_que_nadie_ha_levantado(db: Session) -> None:
    """SPEC §5.2: no es error. Por eso recipient_address es texto y no una FK."""
    project = f.make_project(db)
    thread = f.make_thread(db, project)

    mensaje = f.make_message(db, project, thread, recipient="pablo.db")
    db.flush()

    assert mensaje.recipient_address == "pablo.db"


def test_las_foreign_keys_se_aplican(db: Session) -> None:
    """Sin PRAGMA foreign_keys=ON esto pasaría en silencio y el aislamiento
    por proyecto dependería solo del código de aplicación."""
    db.add(
        Message(
            project_id="prj_inexistente",
            thread_id="thr_inexistente",
            sender_address="victor.db",
            kind="question",
            subject="x",
            body="y",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_dos_documentos_no_pueden_compartir_ruta_en_un_proyecto(db: Session) -> None:
    """Si no, `GET /docs?path=...` sería ambiguo."""
    project = f.make_project(db)
    f.make_document(db, project, path="20-contracts/api-orders.md")

    with pytest.raises(IntegrityError):
        f.make_document(db, project, path="20-contracts/api-orders.md")


def test_la_misma_ruta_en_proyectos_distintos_si_convive(db: Session) -> None:
    """La unicidad es por proyecto: es la frontera dura, no un espacio global."""
    uno = f.make_project(db, slug="proyecto-pablo")
    otro = f.make_project(db, slug="proyecto-luis")

    f.make_document(db, uno, path="20-contracts/api-orders.md")
    f.make_document(db, otro, path="20-contracts/api-orders.md")
    db.flush()

    assert db.query(Document).count() == 2


def test_no_puede_haber_dos_versiones_con_el_mismo_numero(db: Session) -> None:
    """Rompería el control de concurrencia optimista de `base_version`."""
    project = f.make_project(db)
    documento = f.make_document(db, project)

    for _ in range(2):
        db.add(
            DocumentVersion(
                document_id=documento.id,
                version=1,
                content="…",
                intent="create",
                author_address="victor.db",
            )
        )

    with pytest.raises(IntegrityError):
        db.flush()


def test_un_documento_nace_en_version_cero(db: Session) -> None:
    """Todavía no hay contenido: la primera aportación con intent=create lo sube a 1."""
    project = f.make_project(db)

    documento = f.make_document(db, project)

    assert documento.current_version == 0


def test_una_sesion_nace_activa_y_con_ultima_señal(db: Session) -> None:
    project = f.make_project(db)
    person = f.make_person(db)

    sesion = f.make_session(db, project, person)

    assert sesion.status == "active"
    assert sesion.last_seen_at is not None
    assert sesion.session_key.startswith("ses_")


def test_dos_sesiones_de_la_misma_persona_con_roles_distintos_conviven(
    db: Session,
) -> None:
    """SPEC §3.2: mismo token, sesiones distintas. Es correcto y deseado."""
    project = f.make_project(db)
    victor = f.make_person(db, "victor")

    backend = f.make_session(db, project, victor, role="backend")
    base_datos = f.make_session(db, project, victor, role="db")
    db.flush()

    assert backend.session_key != base_datos.session_key
