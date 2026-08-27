"""M1: el proceso responde y la base de datos contesta."""

from fastapi.testclient import TestClient


def test_healthz_responde_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_la_raiz_redirige_al_panel(client: TestClient) -> None:
    """Quien recibe la URL "pelona" del servicio debe caer en el login del panel,
    no en un 404. La API y la salud siguen en sus rutas; la raíz nunca fue ninguna.
    """
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin"
