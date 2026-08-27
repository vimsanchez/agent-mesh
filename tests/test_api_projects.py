"""M4: `GET /projects` y el bootstrap de SPEC §3.2.

Incluye las pruebas críticas de §11 sobre bootstrap y aislamiento.
"""

from fastapi.testclient import TestClient

from tests.conftest import Mundo

V1 = "/api/v1"


# ---------------------------------------------------------------- autenticación


def test_sin_token_no_se_pasa(client: TestClient) -> None:
    respuesta = client.get(f"{V1}/projects")

    assert respuesta.status_code == 401
    assert "MESH_TOKEN" in respuesta.json()["detail"], "el detail debe decir qué falta"


def test_un_token_inventado_da_401(client: TestClient) -> None:
    respuesta = client.get(
        f"{V1}/projects", headers={"Authorization": "Bearer amt_esto-no-existe-para-nada"}
    )

    assert respuesta.status_code == 401
    assert "detente" in respuesta.json()["detail"]


def test_una_cabecera_mal_formada_da_401(client: TestClient, mundo: Mundo) -> None:
    respuesta = client.get(f"{V1}/projects", headers={"Authorization": mundo.tokens["victor"]})

    assert respuesta.status_code == 401
    assert "Bearer" in respuesta.json()["detail"]


# -------------------------------------------------------------- GET /projects


def test_devuelve_solo_los_proyectos_de_la_persona(client: TestClient, mundo: Mundo) -> None:
    """Prueba crítica de §11."""
    victor = client.get(f"{V1}/projects", headers=mundo.auth("victor")).json()
    pablo = client.get(f"{V1}/projects", headers=mundo.auth("pablo")).json()

    assert victor["person"] == "victor"
    assert {p["slug"] for p in victor["projects"]} == {"proyecto-pablo", "proyecto-luis"}
    assert {p["slug"] for p in pablo["projects"]} == {"proyecto-pablo"}


def test_trae_los_miembros_de_cada_proyecto(client: TestClient, mundo: Mundo) -> None:
    datos = client.get(f"{V1}/projects", headers=mundo.auth("victor")).json()

    por_slug = {p["slug"]: set(p["members"]) for p in datos["projects"]}
    assert por_slug["proyecto-pablo"] == {"victor", "pablo"}
    assert por_slug["proyecto-luis"] == {"victor", "luis"}


def test_una_persona_sin_proyectos_recibe_lista_vacia(
    client: TestClient, db: object, mundo: Mundo
) -> None:
    """No es un error: significa "todavía no te agregan" (SPEC §3.2)."""
    from app.db.session import SessionLocal
    from app.services import identity

    with SessionLocal() as sesion:
        sola = identity.create_person(sesion, email="sola@e.test", display_name="sola")
        token = identity.issue_token(sesion, person=sola).plain
        sesion.commit()

    respuesta = client.get(f"{V1}/projects", headers={"Authorization": f"Bearer {token}"})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"person": "sola", "projects": []}


# ------------------------------------- no hay forma de crear proyectos (regla 9)


def test_no_existe_post_projects(client: TestClient, mundo: Mundo) -> None:
    """Regla 9: ni siquiera por conveniencia en desarrollo."""
    respuesta = client.post(
        f"{V1}/projects",
        headers=mundo.auth("victor"),
        json={"slug": "inventado", "name": "X"},
    )

    assert respuesta.status_code == 405, "POST /projects no debe existir"


def test_ninguna_ruta_de_la_api_crea_proyectos(client: TestClient) -> None:
    esquema = client.get("/openapi.json").json()

    escrituras = [
        (ruta, metodo)
        for ruta, ops in esquema["paths"].items()
        for metodo in ops
        if metodo in ("post", "put", "patch") and "project" in ruta
    ]
    assert escrituras == [], f"la API de agentes no debe escribir proyectos: {escrituras}"


# ------------------------------------------------------------------- aislamiento


def test_no_se_ve_el_roster_de_un_proyecto_ajeno(client: TestClient, mundo: Mundo) -> None:
    """Prueba crítica de §11: el proyecto es una frontera dura."""
    respuesta = client.get(f"{V1}/projects/proyecto-luis/roster", headers=mundo.auth("pablo"))

    assert respuesta.status_code == 403
    assert "administrador" in respuesta.json()["detail"]


def test_el_403_dice_que_hacer_y_que_no(client: TestClient, mundo: Mundo) -> None:
    """Regla 10: un agente con un error vago improvisa probando slugs."""
    detalle = client.get(
        f"{V1}/projects/proyecto-luis/roster", headers=mundo.auth("pablo")
    ).json()["detail"]

    assert "no eres miembro" not in detalle.lower(), "no basta decir qué pasó"
    assert "pídele a tu administrador" in detalle
    assert "No pruebes otros slugs" in detalle


def test_un_proyecto_inexistente_da_404(client: TestClient, mundo: Mundo) -> None:
    respuesta = client.get(f"{V1}/projects/no-existe-este/roster", headers=mundo.auth("victor"))

    assert respuesta.status_code == 404
    assert "detente" in respuesta.json()["detail"]
