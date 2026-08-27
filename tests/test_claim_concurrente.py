"""M5: el reclamo atómico, con hilos de verdad.

Prueba crítica de SPEC §11. **No vale una versión secuencial**: lo que se está
comprobando es que entre leer y escribir no cabe otra sesión, y eso solo se ve
cuando dos hilos empujan al mismo tiempo (regla 4).
"""

import threading

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AgentSession, Message, MessageDelivery
from app.db.session import SessionLocal
from app.services import messaging
from tests.conftest import Mundo

V1 = "/api/v1"
COMPETIDORAS = 8


def _registrar(client: TestClient, mundo: Mundo, persona: str, rol: str) -> dict:
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth(persona),
        json={"project": "proyecto-pablo", "role": rol},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _mensaje_suelto(client: TestClient, mundo: Mundo) -> str:
    victor = _registrar(client, mundo, "victor", "db")
    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", victor["session_key"]),
        json={"to": "pablo.general", "subject": "¿cursor u offset?", "body": "…"},
    )
    return str(respuesta.json()["id"])


def test_n_hilos_reclaman_y_gana_exactamente_uno(client: TestClient, mundo: Mundo) -> None:
    """El corazón de la regla 4."""
    message_id = _mensaje_suelto(client, mundo)
    sesiones = [
        _registrar(client, mundo, "pablo", "general")["session_key"]
        for _ in range(COMPETIDORAS)
    ]
    with SessionLocal() as db:
        ids = {
            s.session_key: s.id
            for s in db.scalars(
                select(AgentSession).where(AgentSession.session_key.in_(sesiones))
            )
        }

    ganadores: list[str] = []
    candado = threading.Lock()
    # La barrera es lo que hace real la carrera: sin ella los hilos arrancarían
    # escalonados y el primero ganaría siempre sin competir con nadie.
    barrera = threading.Barrier(COMPETIDORAS)

    def competir(session_key: str) -> None:
        session_id = ids[session_key]
        barrera.wait()
        with SessionLocal() as db:
            gano = messaging.try_claim(db, message_id=message_id, session_id=session_id)
            db.commit()
        if gano:
            with candado:
                ganadores.append(session_id)

    hilos = [threading.Thread(target=competir, args=(k,)) for k in sesiones]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)

    assert all(not h.is_alive() for h in hilos), "algún hilo se quedó colgado"
    assert len(ganadores) == 1, f"ganaron {len(ganadores)} de {COMPETIDORAS}"

    with SessionLocal() as db:
        message = db.get(Message, message_id)
        assert message is not None
        assert message.claimed_by_session_id == ganadores[0]


def test_reclamar_lo_ya_reclamado_devuelve_false(client: TestClient, mundo: Mundo) -> None:
    """Perder el reclamo no es un fallo: significa que ya lo atiende alguien."""
    message_id = _mensaje_suelto(client, mundo)
    una = _registrar(client, mundo, "pablo", "general")
    otra = _registrar(client, mundo, "pablo", "general")

    with SessionLocal() as db:
        ids = {
            s.session_key: s.id
            for s in db.scalars(
                select(AgentSession).where(
                    AgentSession.session_key.in_([una["session_key"], otra["session_key"]])
                )
            )
        }
    with SessionLocal() as db:
        primero = messaging.try_claim(
            db, message_id=message_id, session_id=ids[una["session_key"]]
        )
        db.commit()
    with SessionLocal() as db:
        segundo = messaging.try_claim(
            db, message_id=message_id, session_id=ids[otra["session_key"]]
        )
        db.commit()

    assert primero is True
    assert segundo is False


def test_inbox_concurrente_entrega_el_mensaje_una_sola_vez(
    client: TestClient, mundo: Mundo
) -> None:
    """La misma carrera, pero por el camino real que recorre un agente.

    Ocho sesiones `pablo.general` haciendo inbox a la vez: el mensaje debe
    entregarse una sola vez en total, no ocho.
    """
    message_id = _mensaje_suelto(client, mundo)
    sesiones = [
        _registrar(client, mundo, "pablo", "general")["session_key"]
        for _ in range(COMPETIDORAS)
    ]

    recibidos: list[str] = []
    candado = threading.Lock()
    barrera = threading.Barrier(COMPETIDORAS)

    def leer(session_key: str) -> None:
        barrera.wait()
        respuesta = client.get(
            f"{V1}/inbox?wait=0",
            headers={
                "Authorization": f"Bearer {mundo.tokens['pablo']}",
                "X-Mesh-Session": session_key,
            },
        )
        assert respuesta.status_code == 200, respuesta.text
        for m in respuesta.json()["messages"]:
            with candado:
                recibidos.append(f"{session_key}:{m['id']}")

    hilos = [threading.Thread(target=leer, args=(k,)) for k in sesiones]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert all(not h.is_alive() for h in hilos), "algún hilo se quedó colgado"
    assert len(recibidos) == 1, f"se entregó {len(recibidos)} veces: {recibidos}"

    with SessionLocal() as db:
        entregas = list(
            db.scalars(select(MessageDelivery).where(MessageDelivery.message_id == message_id))
        )
        assert len(entregas) == 1, "una sola fila de entrega"
