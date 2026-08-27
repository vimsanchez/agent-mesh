"""M1: el proceso responde y la base de datos contesta."""

from fastapi.testclient import TestClient


def test_healthz_responde_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
