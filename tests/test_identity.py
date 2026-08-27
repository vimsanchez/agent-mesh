"""M3: lógica de identidad. Alta de admins, personas, proyectos y tokens."""

import re

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AccessToken
from app.services import identity
from app.services.errors import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)

SETTINGS = get_settings()


# ------------------------------------------------ el dominio del panel (regla 6)


def test_un_admin_de_otro_dominio_es_rechazado(db: Session) -> None:
    """Prueba crítica de SPEC §11."""
    with pytest.raises(ValidationFailedError, match=re.escape("empresa-interna.test")):
        identity.create_admin(
            db,
            email="ajeno@otraempresa.com",
            password="contraseña-larga-1",
            settings=SETTINGS,
        )


def test_el_dominio_publico_no_sirve_para_entrar_al_panel(db: Session) -> None:
    """Regla 6: son variables sin relación.

    Si alguien derivara una de la otra, un correo del dominio público del
    servicio abriría el panel. Esto lo atrapa.
    """
    correo_del_dominio_publico = f"colado@{SETTINGS.public_service_domain}"

    with pytest.raises(ValidationFailedError):
        identity.create_admin(
            db,
            email=correo_del_dominio_publico,
            password="contraseña-larga-1",
            settings=SETTINGS,
        )


def test_un_admin_del_dominio_correcto_pasa(db: Session) -> None:
    admin = identity.create_admin(
        db,
        email="nuevo@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )

    assert admin.email == "nuevo@empresa-interna.test"
    assert admin.password_hash != "contraseña-larga-1"


def test_no_se_repite_el_correo_de_un_admin(db: Session) -> None:
    identity.create_admin(
        db,
        email="uno@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )

    with pytest.raises(ConflictError):
        identity.create_admin(
            db,
            email="UNO@empresa-interna.test",
            password="otra-contraseña-1",
            settings=SETTINGS,
        )


# ------------------------------------------------------------------- bootstrap


def test_el_bootstrap_crea_el_admin_con_contraseña_forzada(db: Session) -> None:
    resultado = identity.bootstrap_admin(db, SETTINGS)

    assert resultado is not None
    admin, password = resultado
    assert admin.email == SETTINGS.bootstrap_admin_email
    assert admin.role == "owner"
    assert admin.must_change_password is True
    assert len(password) >= 20
    assert admin.password_hash != password


def test_el_bootstrap_es_idempotente(db: Session) -> None:
    """Reiniciar el contenedor no debe generar credenciales nuevas."""
    primero = identity.bootstrap_admin(db, SETTINGS)
    assert primero is not None

    assert identity.bootstrap_admin(db, SETTINGS) is None


# ---------------------------------------------------------------- autenticación


def test_login_correcto(db: Session) -> None:
    identity.create_admin(
        db,
        email="a@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )

    admin = identity.authenticate_admin(
        db, email="a@empresa-interna.test", password="contraseña-larga-1"
    )

    assert admin is not None
    assert admin.last_login_at is not None


def test_login_con_contraseña_mala_y_con_correo_inexistente_dan_lo_mismo(
    db: Session,
) -> None:
    """Ninguno de los dos debe revelar qué correos están dados de alta."""
    identity.create_admin(
        db,
        email="a@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )

    mala = identity.authenticate_admin(
        db, email="a@empresa-interna.test", password="incorrecta-larga-1"
    )
    inexistente = identity.authenticate_admin(
        db, email="nadie@empresa-interna.test", password="contraseña-larga-1"
    )

    assert mala is None
    assert inexistente is None


def test_un_admin_desactivado_no_entra(db: Session) -> None:
    admin = identity.create_admin(
        db,
        email="a@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )
    admin.is_active = False
    db.flush()

    assert (
        identity.authenticate_admin(
            db, email="a@empresa-interna.test", password="contraseña-larga-1"
        )
        is None
    )


def test_cambiar_contraseña_levanta_la_bandera(db: Session) -> None:
    admin = identity.create_admin(
        db,
        email="a@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
        must_change_password=True,
    )

    identity.change_admin_password(db, admin, "una-contraseña-nueva-larga")

    assert admin.must_change_password is False
    assert identity.authenticate_admin(
        db, email="a@empresa-interna.test", password="una-contraseña-nueva-larga"
    )


def test_una_contraseña_corta_es_rechazada(db: Session) -> None:
    admin = identity.create_admin(
        db,
        email="a@empresa-interna.test",
        password="contraseña-larga-1",
        settings=SETTINGS,
    )

    with pytest.raises(ValidationFailedError, match="12"):
        identity.change_admin_password(db, admin, "corta")


# ------------------------------------------------------------------- proyectos


def test_crear_proyecto(db: Session) -> None:
    project = identity.create_project(db, slug="proyecto-pablo", name="Plataforma de pedidos")

    assert project.slug == "proyecto-pablo"


@pytest.mark.parametrize(
    "slug_malo",
    ["Proyecto Pablo", "proyecto_pablo", "-pablo", "pablo-", "pro--yecto", "", "ñoño"],
)
def test_un_slug_mal_formado_es_rechazado(db: Session, slug_malo: str) -> None:
    with pytest.raises(ValidationFailedError):
        identity.create_project(db, slug=slug_malo, name="X")


def test_el_slug_se_normaliza_a_minusculas(db: Session) -> None:
    """Un agente escribe `--project` a mano; que MAYÚSCULAS funcione es cortesía,
    no laxitud: lo que se guarda y se compara es siempre la versión minúscula."""
    project = identity.create_project(db, slug="  Proyecto-PABLO  ", name="P")

    assert project.slug == "proyecto-pablo"


def test_no_se_repite_el_slug(db: Session) -> None:
    identity.create_project(db, slug="proyecto-pablo", name="Uno")

    with pytest.raises(ConflictError):
        identity.create_project(db, slug="proyecto-pablo", name="Otro")


# -------------------------------------------------------------------- personas


def test_crear_persona(db: Session) -> None:
    person = identity.create_person(db, email="victor@ejemplo.test", display_name="Victor")

    assert person.display_name == "victor", "el nombre se normaliza a minúsculas"


def test_un_nombre_con_punto_es_rechazado(db: Session) -> None:
    """El punto separa persona de rol en `victor.db`; uno de más rompe el parseo."""
    with pytest.raises(ValidationFailedError, match="punto"):
        identity.create_person(db, email="v@ejemplo.test", display_name="victor.db")


def test_no_se_repite_el_nombre_de_persona(db: Session) -> None:
    identity.create_person(db, email="uno@ejemplo.test", display_name="victor")

    with pytest.raises(ConflictError):
        identity.create_person(db, email="otro@ejemplo.test", display_name="victor")


# ------------------------------------------------------------------ membresías


def test_agregar_y_quitar_miembro(db: Session) -> None:
    project = identity.create_project(db, slug="proyecto-pablo", name="P")
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")

    identity.add_member(db, project=project, person=person)
    assert identity.project_members(db, project) == [person]
    assert identity.projects_of_person(db, person) == [project]

    identity.remove_member(db, project=project, person=person)
    assert identity.project_members(db, project) == []


def test_no_se_agrega_dos_veces_al_mismo_miembro(db: Session) -> None:
    project = identity.create_project(db, slug="proyecto-pablo", name="P")
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    identity.add_member(db, project=project, person=person)

    with pytest.raises(ConflictError):
        identity.add_member(db, project=project, person=person)


def test_quitar_a_quien_no_es_miembro_falla(db: Session) -> None:
    project = identity.create_project(db, slug="proyecto-pablo", name="P")
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")

    with pytest.raises(NotFoundError):
        identity.remove_member(db, project=project, person=person)


def test_una_persona_sin_proyectos_recibe_lista_vacia(db: Session) -> None:
    """SPEC §3.2: lista vacía es válida y significa "todavía no te agregan"."""
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")

    assert identity.projects_of_person(db, person) == []


# ---------------------------------------------------------------------- tokens


def test_el_token_en_claro_no_se_guarda(db: Session) -> None:
    """Lo único que vive en la base es el hash."""
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")

    emitido = identity.issue_token(db, person=person, label="laptop")
    db.flush()

    guardados = [t.token_hash for t in db.query(AccessToken).all()]
    assert emitido.plain not in guardados
    assert emitido.record.token_hash in guardados


def test_resolver_un_token_devuelve_su_persona(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person)

    assert identity.resolve_token(db, emitido.plain) is person


def test_resolver_marca_el_ultimo_uso(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person)
    assert emitido.record.last_used_at is None

    identity.resolve_token(db, emitido.plain)

    assert emitido.record.last_used_at is not None


def test_un_token_revocado_ya_no_resuelve(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person)
    identity.revoke_token(db, emitido.record.id)

    with pytest.raises(UnauthorizedError, match="avísale a tu persona"):
        identity.resolve_token(db, emitido.plain)


def test_revocar_no_borra_el_rastro(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person, label="la vieja")

    identity.revoke_token(db, emitido.record.id)

    assert emitido.record.revoked_at is not None
    assert emitido.record.label == "la vieja"
    assert db.get(AccessToken, emitido.record.id) is not None


def test_revocar_dos_veces_no_cambia_la_fecha(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person)

    primera = identity.revoke_token(db, emitido.record.id).revoked_at
    segunda = identity.revoke_token(db, emitido.record.id).revoked_at

    assert primera == segunda


def test_un_token_inventado_no_resuelve(db: Session) -> None:
    with pytest.raises(UnauthorizedError):
        identity.resolve_token(db, "amt_esto-no-existe-pero-tiene-el-largo-suficiente")


def test_un_token_de_una_persona_desactivada_no_resuelve(db: Session) -> None:
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")
    emitido = identity.issue_token(db, person=person)
    person.is_active = False
    db.flush()

    with pytest.raises(UnauthorizedError):
        identity.resolve_token(db, emitido.plain)


def test_una_persona_puede_tener_varios_tokens(db: Session) -> None:
    """Una máquina distinta por token: servidor, laptop, VS Code (SPEC §3.2)."""
    person = identity.create_person(db, email="v@ejemplo.test", display_name="victor")

    servidor = identity.issue_token(db, person=person, label="servidor")
    laptop = identity.issue_token(db, person=person, label="laptop")

    assert identity.resolve_token(db, servidor.plain) is person
    assert identity.resolve_token(db, laptop.plain) is person
    assert len(identity.tokens_of_person(db, person)) == 2
