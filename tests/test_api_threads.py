"""Delta v0.2, C3: resolver hilos, listarlos, y reapertura automática."""

from fastapi.testclient import TestClient

from tests.conftest import Mundo

V1 = "/api/v1"


def _registrar(
    client: TestClient, mundo: Mundo, persona: str, rol: str, slug: str = "proyecto-pablo"
) -> dict:
    respuesta = client.post(
        f"{V1}/sessions", headers=mundo.auth(persona), json={"project": slug, "role": rol}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _enviar(client: TestClient, mundo: Mundo, persona: str, sesion: dict, **cuerpo) -> dict:
    payload = {"to": "pablo.general", "subject": "un tema", "body": "…", **cuerpo}
    respuesta = client.post(
        f"{V1}/messages", headers=mundo.sesion(persona, sesion["session_key"]), json=payload
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_resolve_cierra_y_es_idempotente(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    cabeceras = mundo.sesion("victor", victor["session_key"])
    enviado = _enviar(client, mundo, "victor", victor)

    primera = client.post(f"{V1}/threads/{enviado['thread_id']}/resolve", headers=cabeceras)
    assert primera.status_code == 200, primera.text
    assert primera.json() == {
        "id": enviado["thread_id"],
        "subject": "un tema",
        "status": "resolved",
    }

    segunda = client.post(f"{V1}/threads/{enviado['thread_id']}/resolve", headers=cabeceras)
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "resolved"


def test_send_a_hilo_resuelto_lo_reabre(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    cabeceras = mundo.sesion("victor", victor["session_key"])
    enviado = _enviar(client, mundo, "victor", victor)
    client.post(f"{V1}/threads/{enviado['thread_id']}/resolve", headers=cabeceras)

    reabierto = _enviar(client, mundo, "victor", victor, thread_id=enviado["thread_id"])
    assert reabierto["thread_status"] == "open"

    hilo = client.get(f"{V1}/threads/{enviado['thread_id']}", headers=cabeceras).json()
    assert hilo["status"] == "open"


def test_threads_lista_con_conteo_y_filtro(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    cabeceras = mundo.sesion("victor", victor["session_key"])
    abierto = _enviar(client, mundo, "victor", victor, subject="sigue abierto")
    resuelto = _enviar(client, mundo, "victor", victor, subject="ya cerró")
    client.post(f"{V1}/threads/{resuelto['thread_id']}/resolve", headers=cabeceras)

    todos = client.get(f"{V1}/threads", headers=cabeceras).json()["threads"]
    assert {t["id"] for t in todos} == {abierto["thread_id"], resuelto["thread_id"]}
    assert all(
        {"id", "subject", "status", "message_count", "updated_at"} <= t.keys() for t in todos
    )

    abiertos = client.get(f"{V1}/threads", params={"status": "open"}, headers=cabeceras).json()[
        "threads"
    ]
    assert [t["id"] for t in abiertos] == [abierto["thread_id"]]
    assert abiertos[0]["message_count"] == 1


def test_un_status_inventado_se_rechaza(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    cabeceras = mundo.sesion("victor", victor["session_key"])

    respuesta = client.get(f"{V1}/threads", params={"status": "cerradisimo"}, headers=cabeceras)
    assert respuesta.status_code == 422


def test_threads_no_filtra_hilos_de_otros_proyectos(client: TestClient, mundo: Mundo) -> None:
    """Aislamiento (regla 2): ni listar ni resolver cruza la frontera del proyecto."""
    victor = _registrar(client, mundo, "victor", "db")
    luis = _registrar(client, mundo, "luis", "general", slug="proyecto-luis")
    cabeceras_victor = mundo.sesion("victor", victor["session_key"])

    ajeno = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("luis", luis["session_key"]),
        json={"to": "victor.general", "subject": "tema de luis", "body": "…"},
    ).json()

    visibles = client.get(f"{V1}/threads", headers=cabeceras_victor).json()["threads"]
    assert ajeno["thread_id"] not in {t["id"] for t in visibles}

    intruso = client.post(
        f"{V1}/threads/{ajeno['thread_id']}/resolve", headers=cabeceras_victor
    )
    assert intruso.status_code == 404
