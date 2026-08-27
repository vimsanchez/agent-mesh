"""M3: el panel, ejercitado por HTTP como lo usaría un navegador.

Cubre la compuerta de `must_change_password`, que es la que evita que la
contraseña impresa en el log del contenedor sirva para navegar el panel.
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AccessToken, AdminUser
from app.security import tokens
from app.services import identity
from app.services.errors import UnauthorizedError

SETTINGS = get_settings()
CONTRASEÑA = "una-contraseña-de-pruebas"


def _admin_listo(db: Session, email: str = "jefe@empresa-interna.test") -> AdminUser:
    """Admin que ya cambió su contraseña, para no repetir el flujo en cada prueba."""
    admin = identity.create_admin(db, email=email, password=CONTRASEÑA, settings=SETTINGS)
    db.commit()
    return admin


def _entrar(client: TestClient, email: str, password: str = CONTRASEÑA) -> None:
    respuesta = client.post("/admin/login", data={"email": email, "password": password})
    assert respuesta.status_code == 200, respuesta.status_code


# ------------------------------------------------------------------- bootstrap


def test_el_arranque_crea_el_admin_inicial(client: TestClient, db: Session) -> None:
    client.get("/admin/login")

    admin = db.query(AdminUser).filter_by(email=SETTINGS.bootstrap_admin_email).one()
    assert admin.must_change_password is True
    assert admin.role == "owner"


def test_la_contraseña_de_bootstrap_no_queda_en_la_base(
    client: TestClient, db: Session
) -> None:
    """Solo el hash. La contraseña en claro vive únicamente en el log."""
    client.get("/admin/login")

    admin = db.query(AdminUser).filter_by(email=SETTINGS.bootstrap_admin_email).one()
    assert admin.password_hash.startswith("$argon2id$")


# ------------------------------------------------------------------------ login


def test_el_login_se_muestra_sin_credenciales(client: TestClient) -> None:
    respuesta = client.get("/admin/login")

    assert respuesta.status_code == 200
    assert "Panel de administración" in respuesta.text


def test_sin_sesion_el_panel_redirige_al_login(client: TestClient) -> None:
    respuesta = client.get("/admin", follow_redirects=False)

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/admin/login"


def test_credenciales_malas_no_dejan_entrar(client: TestClient, db: Session) -> None:
    _admin_listo(db)

    respuesta = client.post(
        "/admin/login", data={"email": "jefe@empresa-interna.test", "password": "mala"}
    )

    assert "incorrectos" in respuesta.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_el_mensaje_de_error_no_revela_si_el_correo_existe(
    client: TestClient, db: Session
) -> None:
    _admin_listo(db)

    existente = client.post(
        "/admin/login", data={"email": "jefe@empresa-interna.test", "password": "mala"}
    )
    inventado = client.post(
        "/admin/login", data={"email": "nadie@empresa-interna.test", "password": "mala"}
    )

    assert "incorrectos" in existente.text
    assert "incorrectos" in inventado.text


def test_con_credenciales_buenas_se_entra(client: TestClient, db: Session) -> None:
    _admin_listo(db)

    _entrar(client, "jefe@empresa-interna.test")

    resumen = client.get("/admin")
    assert resumen.status_code == 200
    assert "Resumen" in resumen.text


def test_salir_cierra_la_sesion(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    client.get("/admin/logout")

    assert client.get("/admin", follow_redirects=False).status_code == 303


# ------------------------------------------------- compuerta de must_change_password


def test_con_contraseña_forzada_el_panel_manda_a_cambiarla(
    client: TestClient, db: Session
) -> None:
    """La contraseña de bootstrap salió en un log; quien lo lea la conoce.

    Así que entrar con ella no debe permitir navegar el panel.
    """
    identity.create_admin(
        db,
        email="nuevo@empresa-interna.test",
        password=CONTRASEÑA,
        settings=SETTINGS,
        must_change_password=True,
    )
    db.commit()

    client.post(
        "/admin/login",
        data={"email": "nuevo@empresa-interna.test", "password": CONTRASEÑA},
    )

    for ruta in ("/admin", "/admin/projects", "/admin/people"):
        respuesta = client.get(ruta, follow_redirects=False)
        assert respuesta.status_code == 303, ruta
        assert respuesta.headers["location"] == "/admin/password", ruta


def test_tras_cambiar_la_contraseña_se_abre_el_panel(client: TestClient, db: Session) -> None:
    identity.create_admin(
        db,
        email="nuevo@empresa-interna.test",
        password=CONTRASEÑA,
        settings=SETTINGS,
        must_change_password=True,
    )
    db.commit()
    client.post(
        "/admin/login",
        data={"email": "nuevo@empresa-interna.test", "password": CONTRASEÑA},
    )

    client.post(
        "/admin/password",
        data={"password": "la-nueva-de-verdad-12", "repeat": "la-nueva-de-verdad-12"},
    )

    assert client.get("/admin").status_code == 200


def test_dos_contraseñas_distintas_no_pasan(client: TestClient, db: Session) -> None:
    identity.create_admin(
        db,
        email="nuevo@empresa-interna.test",
        password=CONTRASEÑA,
        settings=SETTINGS,
        must_change_password=True,
    )
    db.commit()
    client.post(
        "/admin/login",
        data={"email": "nuevo@empresa-interna.test", "password": CONTRASEÑA},
    )

    respuesta = client.post(
        "/admin/password", data={"password": "una-larga-12345", "repeat": "otra-larga-12345"}
    )

    assert "no coinciden" in respuesta.text


# ------------------------------------------------------------------------- CRUD


def test_crear_proyecto_desde_el_panel(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    respuesta = client.post(
        "/admin/projects", data={"slug": "proyecto-pablo", "name": "Plataforma"}
    )

    assert "proyecto-pablo" in respuesta.text
    assert identity.get_project_by_slug(db, "proyecto-pablo") is not None


def test_un_slug_invalido_muestra_el_motivo(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    respuesta = client.post("/admin/projects", data={"slug": "Proyecto Pablo!", "name": "X"})

    assert "no sirve como slug" in respuesta.text


def test_alta_de_persona_y_membresia(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    client.post("/admin/projects", data={"slug": "proyecto-pablo", "name": "P"})

    client.post("/admin/people", data={"display_name": "victor", "email": "v@ejemplo.test"})
    person = identity.list_people(db)[0]
    client.post("/admin/projects/proyecto-pablo/members", data={"person_id": person.id})

    detalle = client.get("/admin/projects/proyecto-pablo")
    assert "victor" in detalle.text
    assert identity.projects_of_person(db, person)[0].slug == "proyecto-pablo"


def test_quitar_membresia(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    client.post("/admin/projects", data={"slug": "proyecto-pablo", "name": "P"})
    client.post("/admin/people", data={"display_name": "victor", "email": "v@ejemplo.test"})
    person = identity.list_people(db)[0]
    client.post("/admin/projects/proyecto-pablo/members", data={"person_id": person.id})

    client.post(f"/admin/projects/proyecto-pablo/members/{person.id}/remove")

    db.expire_all()
    assert identity.projects_of_person(db, person) == []


# ------------------------------------------------------------------------ tokens


def _emitir_token(client: TestClient, db: Session) -> str:
    """Emite un token por el panel y devuelve el valor en claro que se mostró."""
    client.post("/admin/people", data={"display_name": "victor", "email": "v@ejemplo.test"})
    person = identity.list_people(db)[0]
    respuesta = client.post(f"/admin/people/{person.id}/tokens", data={"label": "laptop"})
    encontrado = re.search(r"amt_[A-Za-z0-9_-]{20,}", respuesta.text)
    assert encontrado, "el panel debe mostrar el token una vez"
    return encontrado.group(0)


def test_el_token_se_muestra_una_sola_vez(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    plano = _emitir_token(client, db)

    person = identity.list_people(db)[0]
    de_nuevo = client.get(f"/admin/people/{person.id}")
    assert plano not in de_nuevo.text, "recargar no debe volver a mostrar el token"


def test_el_token_emitido_sirve_para_autenticarse(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    plano = _emitir_token(client, db)

    db.expire_all()
    person = identity.resolve_token(db, plano)
    assert person.display_name == "victor"


def test_en_la_base_solo_queda_el_hash(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    plano = _emitir_token(client, db)

    db.expire_all()
    almacenados = [t.token_hash for t in db.query(AccessToken).all()]
    assert plano not in almacenados
    assert tokens.hash_token(plano) in almacenados


def test_revocar_desde_el_panel_invalida_el_token(client: TestClient, db: Session) -> None:
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    plano = _emitir_token(client, db)
    db.expire_all()
    person = identity.list_people(db)[0]
    token_id = identity.tokens_of_person(db, person)[0].id

    client.post(f"/admin/people/{person.id}/tokens/{token_id}/revoke")

    db.expire_all()
    with pytest.raises(UnauthorizedError):
        identity.resolve_token(db, plano)


# ----------------------------------------------- el panel no está en la API pública


def test_el_panel_no_aparece_en_el_esquema_openapi(client: TestClient) -> None:
    """El panel no es parte del contrato de agentes."""
    esquema = client.get("/openapi.json").json()

    assert not [ruta for ruta in esquema["paths"] if ruta.startswith("/admin")]
    assert "/healthz" in esquema["paths"]


def test_ninguna_contraseña_sale_por_http(client: TestClient, db: Session) -> None:
    """La de bootstrap sí va al log —SPEC §9 lo exige, una vez— pero jamás por HTTP."""
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    for ruta in ("/admin", "/admin/projects", "/admin/people"):
        cuerpo = client.get(ruta).text
        assert CONTRASEÑA not in cuerpo, ruta
        assert "argon2" not in cuerpo.lower(), ruta
        assert "password_hash" not in cuerpo, ruta


# --------------------------------------- vistas de solo lectura (SPEC §10.8)

V1 = "/api/v1"


def _escenario_de_agentes(client: TestClient, db: Session) -> tuple[str, str]:
    """Un proyecto con un hilo y un documento, creados por la API de agentes.

    El panel se prueba sobre datos reales generados por el camino normal, no
    insertados a mano: así también se comprueba que las dos mitades del sistema
    ven lo mismo.
    """
    from app.services import identity as ident

    project = ident.create_project(db, slug="proyecto-pablo", name="Pedidos")
    victor = ident.create_person(db, email="v@e.test", display_name="victor")
    ident.add_member(db, project=project, person=victor)
    token = ident.issue_token(db, person=victor).plain
    db.commit()

    auth = {"Authorization": f"Bearer {token}"}
    sesion = client.post(
        f"{V1}/sessions", headers=auth, json={"project": "proyecto-pablo", "role": "db"}
    ).json()
    cab = {**auth, "X-Mesh-Session": sesion["session_key"]}
    client.post(
        f"{V1}/messages",
        headers=cab,
        json={"to": "pablo.general", "subject": "¿cursor u offset?", "body": "Cuerpo largo."},
    )
    client.post(
        f"{V1}/docs/contributions",
        headers=cab,
        json={
            "document_path": "20-contracts/api-orders.md",
            "base_version": 0,
            "intent": "create",
            "content": "# Contrato\n\nPor cursor.",
            "rationale": "primera versión",
        },
    )
    return "proyecto-pablo", token


def test_el_panel_muestra_los_hilos_de_los_agentes(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")

    pagina = client.get(f"/admin/projects/{slug}/threads")

    assert pagina.status_code == 200
    assert "¿cursor u offset?" in pagina.text


def test_el_detalle_del_hilo_muestra_el_cuerpo(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    listado = client.get(f"/admin/projects/{slug}/threads").text
    thread_id = re.search(r"thr_[a-f0-9]+", listado)
    assert thread_id

    pagina = client.get(f"/admin/projects/{slug}/threads/{thread_id.group(0)}")

    assert "Cuerpo largo." in pagina.text
    assert "victor.db" in pagina.text


def test_el_panel_muestra_los_documentos_con_su_historial(
    client: TestClient, db: Session
) -> None:
    slug, _ = _escenario_de_agentes(client, db)
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    listado = client.get(f"/admin/projects/{slug}/docs")
    assert "20-contracts/api-orders.md" in listado.text
    doc_id = re.search(r"doc_[a-f0-9]+", listado.text)
    assert doc_id

    detalle = client.get(f"/admin/projects/{slug}/docs/{doc_id.group(0)}")

    assert "Por cursor." in detalle.text
    assert "primera versión" in detalle.text, "el motivo del historial"
    assert "victor.db" in detalle.text, "el autor"


def test_un_hilo_de_otro_proyecto_no_se_ve_desde_el_panel(
    client: TestClient, db: Session
) -> None:
    """El panel no es una puerta trasera al aislamiento solo porque quien mira
    sea administrador."""
    slug, _ = _escenario_de_agentes(client, db)
    from app.services import identity as ident

    otro = ident.create_project(db, slug="proyecto-luis", name="Portal")
    db.commit()
    _admin_listo(db)
    _entrar(client, "jefe@empresa-interna.test")
    listado = client.get(f"/admin/projects/{slug}/threads").text
    thread_id = re.search(r"thr_[a-f0-9]+", listado)
    assert thread_id

    respuesta = client.get(
        f"/admin/projects/{otro.slug}/threads/{thread_id.group(0)}",
        follow_redirects=False,
    )

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"/admin/projects/{otro.slug}/threads"


def test_las_vistas_de_lectura_exigen_sesion(client: TestClient, db: Session) -> None:
    slug, _ = _escenario_de_agentes(client, db)

    for ruta in (f"/admin/projects/{slug}/threads", f"/admin/projects/{slug}/docs"):
        respuesta = client.get(ruta, follow_redirects=False)
        assert respuesta.status_code == 303, ruta
        assert respuesta.headers["location"] == "/admin/login", ruta


def test_el_panel_sigue_fuera_del_esquema_openapi(client: TestClient) -> None:
    """Las vistas nuevas tampoco pertenecen al contrato de agentes."""
    esquema = client.get("/openapi.json").json()

    assert not [ruta for ruta in esquema["paths"] if ruta.startswith("/admin")]
