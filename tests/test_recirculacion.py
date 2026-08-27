"""M5: qué pasa con lo que quedó sin confirmar cuando una sesión muere.

Prueba crítica de SPEC §11 ("sesión muerta") y de la regla que acordamos para el
§5.5, que dejaba la elección abierta:

- con destinatario -> vuelve a `pending`, para que otra sesión con esa misma
  dirección lo reciba
- sin destinatario -> cae a `unclaimed`
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db.base import utcnow
from app.db.models import AgentSession, Message
from app.db.session import SessionLocal
from tests.conftest import Mundo

V1 = "/api/v1"
SETTINGS = get_settings()


def _registrar(client: TestClient, mundo: Mundo, persona: str, rol: str) -> dict:
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth(persona),
        json={"project": "proyecto-pablo", "role": rol},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _enviar(client: TestClient, mundo: Mundo, sesion: dict, to: str | None) -> dict:
    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", sesion["session_key"]),
        json={"to": to, "subject": "¿cursor u offset?", "body": "…"},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _matar(session_key: str) -> None:
    """Envejece el latido más allá del umbral. La caducidad es perezosa, así que
    esto solo prepara el terreno: el cambio ocurre cuando alguien lee."""
    with SessionLocal() as db:
        agent_session = db.scalar(
            select(AgentSession).where(AgentSession.session_key == session_key)
        )
        assert agent_session is not None
        agent_session.last_seen_at = utcnow() - timedelta(
            seconds=SETTINGS.session_stale_after_seconds + 60
        )
        db.commit()


def _estado(message_id: str) -> str:
    with SessionLocal() as db:
        message = db.get(Message, message_id)
        assert message is not None
        return message.status


def _inbox(client: TestClient, mundo: Mundo, persona: str, sesion: dict) -> list[dict]:
    respuesta = client.get(
        f"{V1}/inbox?wait=0", headers=mundo.sesion(persona, sesion["session_key"])
    )
    return list(respuesta.json()["messages"])


# ------------------------------------------------------------------ con destino


def test_un_mensaje_sin_ack_reaparece_para_otra_sesion(
    client: TestClient, mundo: Mundo
) -> None:
    """Prueba crítica de §11.

    Pablo recibe, no confirma, y su sesión muere. El mensaje debe volver a
    circular para que otra sesión `pablo.general` lo atienda.
    """
    victor = _registrar(client, mundo, "victor", "db")
    primera = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    assert len(_inbox(client, mundo, "pablo", primera)) == 1
    assert _estado(enviado["id"]) == "delivered"

    _matar(primera["session_key"])
    relevo = _registrar(client, mundo, "pablo", "general")
    recibidos = _inbox(client, mundo, "pablo", relevo)

    assert [m["id"] for m in recibidos] == [enviado["id"]]


def test_al_recircular_vuelve_a_pending_si_tiene_destinatario(
    client: TestClient, mundo: Mundo
) -> None:
    """La mitad de la regla acordada."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    _inbox(client, mundo, "pablo", pablo)

    _matar(pablo["session_key"])
    # Cualquier lectura del proyecto dispara la caducidad y la recirculación.
    _inbox(client, mundo, "victor", victor)

    assert _estado(enviado["id"]) == "pending"


def test_al_recircular_el_reclamo_se_libera(client: TestClient, mundo: Mundo) -> None:
    """Si el reclamo quedara puesto, ninguna otra sesión podría tomarlo nunca."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    _inbox(client, mundo, "pablo", pablo)

    _matar(pablo["session_key"])
    _inbox(client, mundo, "victor", victor)

    with SessionLocal() as db:
        message = db.get(Message, enviado["id"])
        assert message is not None
        assert message.claimed_by_session_id is None
        assert message.claimed_at is None


# ------------------------------------------------------------------ sin destino


def test_al_recircular_cae_a_unclaimed_si_no_tiene_destinatario(
    client: TestClient, mundo: Mundo
) -> None:
    """La otra mitad: sin dirección a la que volver, va a la bandeja común."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, None)
    with SessionLocal() as db:
        # Se simula que pablo lo reclamó de la bandeja (el flujo del paso 6).
        message = db.get(Message, enviado["id"])
        assert message is not None
        sesion_pablo = db.scalar(
            select(AgentSession).where(AgentSession.session_key == pablo["session_key"])
        )
        assert sesion_pablo is not None
        message.claimed_by_session_id = sesion_pablo.id
        message.recipient_address = None
        from app.db.models import MessageDelivery

        db.add(MessageDelivery(message_id=message.id, session_id=sesion_pablo.id))
        message.status = "delivered"
        db.commit()

    _matar(pablo["session_key"])
    _inbox(client, mundo, "victor", victor)

    assert _estado(enviado["id"]) == "unclaimed"


# ------------------------------------------------------------ lo que NO se toca


def test_lo_ya_confirmado_no_reaparece(client: TestClient, mundo: Mundo) -> None:
    """Ese es el punto del ack: la entrega ya está cerrada."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    _inbox(client, mundo, "pablo", pablo)
    client.post(
        f"{V1}/messages/{enviado['id']}/ack",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    _matar(pablo["session_key"])
    relevo = _registrar(client, mundo, "pablo", "general")

    assert _inbox(client, mundo, "pablo", relevo) == []


def test_un_mensaje_answered_no_recircula(client: TestClient, mundo: Mundo) -> None:
    """Su ciclo terminó; devolverlo a la bandeja sería resucitar una pregunta
    que ya tiene respuesta."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    _inbox(client, mundo, "pablo", pablo)
    client.post(
        f"{V1}/messages",
        headers=mundo.sesion("pablo", pablo["session_key"]),
        json={
            "to": "victor.db",
            "kind": "answer",
            "subject": "cursor",
            "body": "…",
            "in_reply_to": enviado["id"],
        },
    )
    assert _estado(enviado["id"]) == "answered"

    _matar(pablo["session_key"])
    _inbox(client, mundo, "victor", victor)

    assert _estado(enviado["id"]) == "answered"


def test_el_cierre_limpio_tambien_hace_circular_lo_pendiente(
    client: TestClient, mundo: Mundo
) -> None:
    """SPEC §5.5: "Los mensajes entregados sin ack regresan a la bandeja"."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, victor, "pablo.general")
    _inbox(client, mundo, "pablo", pablo)

    client.delete(f"{V1}/sessions/{pablo['session_key']}", headers=mundo.auth("pablo"))
    relevo = _registrar(client, mundo, "pablo", "general")
    recibidos = _inbox(client, mundo, "pablo", relevo)

    assert [m["id"] for m in recibidos] == [enviado["id"]]
