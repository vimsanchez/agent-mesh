"""M6: bandeja de no reclamados, reclamo, descarte y aviso automático."""

import threading

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AgentSession, Message
from app.db.session import SessionLocal
from app.services.messaging import SERVICE_ADDRESS
from tests.conftest import Mundo

V1 = "/api/v1"


def _registrar(
    client: TestClient, mundo: Mundo, persona: str, rol: str, slug: str = "proyecto-pablo"
) -> dict:
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth(persona),
        json={"project": slug, "role": rol},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _enviar(client: TestClient, mundo: Mundo, persona: str, sesion: dict, **cuerpo) -> dict:
    payload = {"subject": "¿cursor u offset?", "body": "…", **cuerpo}
    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion(persona, sesion["session_key"]),
        json=payload,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _unclaimed(client: TestClient, mundo: Mundo, persona: str, sesion: dict) -> list[dict]:
    respuesta = client.get(
        f"{V1}/unclaimed", headers=mundo.sesion(persona, sesion["session_key"])
    )
    assert respuesta.status_code == 200, respuesta.text
    return list(respuesta.json()["messages"])


def _inbox(client: TestClient, mundo: Mundo, persona: str, sesion: dict) -> list[dict]:
    respuesta = client.get(
        f"{V1}/inbox?wait=0", headers=mundo.sesion(persona, sesion["session_key"])
    )
    return list(respuesta.json()["messages"])


# --------------------------------------------------------------------- bandeja


def test_un_mensaje_sin_destinatario_esta_en_la_bandeja(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    assert [m["id"] for m in _unclaimed(client, mundo, "pablo", pablo)] == [enviado["id"]]


def test_un_mensaje_a_un_rol_que_nadie_levanto_esta_en_la_bandeja(
    client: TestClient, mundo: Mundo
) -> None:
    """§5.3: sin destinatario vivo, visible para todas las sesiones del proyecto.

    Y a la vez sigue esperando a `pablo.db` por si aparece: esa es la razón de que
    la bandeja se calcule y no se materialice como estado.
    """
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")

    en_bandeja = _unclaimed(client, mundo, "pablo", pablo)

    assert [m["id"] for m in en_bandeja] == [enviado["id"]]
    assert en_bandeja[0]["status"] == "pending", "sigue esperando, no se degradó"


def test_un_mensaje_con_destinatario_vivo_no_esta_en_la_bandeja(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    # La llamada importa aunque no se use el valor: es lo que pone vivo al
    # destinatario, que es justo lo que saca el mensaje de la bandeja.
    _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")

    assert _unclaimed(client, mundo, "victor", victor) == []


def test_uno_no_ve_en_la_bandeja_lo_que_el_mismo_envio(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    _enviar(client, mundo, "victor", victor, to=None)

    assert _unclaimed(client, mundo, "victor", victor) == []


def test_cuando_el_destinatario_aparece_deja_de_estar_en_la_bandeja(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    otro = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.db")
    assert len(_unclaimed(client, mundo, "pablo", otro)) == 1

    pablo_db = _registrar(client, mundo, "pablo", "db")

    assert _unclaimed(client, mundo, "pablo", otro) == []
    assert len(_inbox(client, mundo, "pablo", pablo_db)) == 1, "le llegó a su dueño"


def test_la_bandeja_no_cruza_proyectos(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    _enviar(client, mundo, "victor", en_luis, to=None)

    assert _unclaimed(client, mundo, "victor", en_pablo) == []


# --------------------------------------------------------------------- reclamo


def test_reclamar_saca_el_mensaje_de_la_bandeja_de_los_demas(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    otra = _registrar(client, mundo, "pablo", "backend")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    assert _unclaimed(client, mundo, "pablo", otra) == []


def test_reclamar_dos_veces_lo_mismo_da_409(client: TestClient, mundo: Mundo) -> None:
    """El 409 no es un fallo: significa que ya lo atiende alguien."""
    victor = _registrar(client, mundo, "victor", "db")
    una = _registrar(client, mundo, "pablo", "general")
    otra = _registrar(client, mundo, "pablo", "backend")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    primera = client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", una["session_key"]),
    )
    segunda = client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", otra["session_key"]),
    )

    assert primera.status_code == 200
    assert segunda.status_code == 409
    assert "sigue adelante" in segunda.json()["detail"]


def test_reclamar_lo_propio_es_idempotente(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)
    cabeceras = mundo.sesion("pablo", pablo["session_key"])

    primera = client.post(f"{V1}/messages/{enviado['id']}/claim", headers=cabeceras)
    segunda = client.post(f"{V1}/messages/{enviado['id']}/claim", headers=cabeceras)

    assert primera.status_code == segunda.status_code == 200


def test_lo_reclamado_llega_por_el_inbox(client: TestClient, mundo: Mundo) -> None:
    """api.md: el inbox devuelve lo dirigido a esta sesión Y lo reclamado por ella."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    with SessionLocal() as db:
        message = db.get(Message, enviado["id"])
        assert message is not None
        assert message.status == "delivered"


def test_no_se_reclama_un_mensaje_de_otro_proyecto(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    ajeno = _enviar(client, mundo, "victor", en_luis, to=None)

    respuesta = client.post(
        f"{V1}/messages/{ajeno['id']}/claim",
        headers=mundo.sesion("victor", en_pablo["session_key"]),
    )

    assert respuesta.status_code == 404


# ------------------------------------------------------------ aviso automático


def test_reclamar_lo_dirigido_a_otro_rol_avisa_al_remitente(
    client: TestClient, mundo: Mundo
) -> None:
    """§5.3: así el emisor sabe quién acabó atendiéndolo."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    avisos = [m for m in _inbox(client, mundo, "victor", victor) if m["kind"] == "notice"]
    assert len(avisos) == 1
    assert avisos[0]["from"] == SERVICE_ADDRESS
    assert "pablo.general" in avisos[0]["subject"]
    assert "No hace falta que reenvíes nada" in avisos[0]["body"]


def test_el_aviso_va_en_el_mismo_hilo(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    hilo = client.get(
        f"{V1}/threads/{enviado['thread_id']}",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()
    assert [m["kind"] for m in hilo["messages"]] == ["question", "notice"]


def test_el_aviso_no_cierra_la_pregunta(client: TestClient, mundo: Mundo) -> None:
    """Es `notice` y no `answer` a propósito: decir quién se hizo cargo no
    responde la pregunta."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    with SessionLocal() as db:
        message = db.get(Message, enviado["id"])
        assert message is not None
        assert message.status != "answered"


def test_reclamar_lo_dirigido_a_uno_mismo_no_genera_aviso(
    client: TestClient, mundo: Mundo
) -> None:
    """No tiene sentido avisar de que lo tomó quien debía tomarlo."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    with SessionLocal() as db:
        avisos = list(
            db.scalars(select(Message).where(Message.sender_address == SERVICE_ADDRESS))
        )
    assert avisos == []


def test_el_aviso_del_servicio_si_aparece_en_la_bandeja_si_nadie_lo_recoge(
    client: TestClient, mundo: Mundo
) -> None:
    """La trampa del NULL en SQL: `sender_session_id != x` con NULL da NULL.

    Los avisos los emite el servicio con `sender_session_id` nulo. Sin tratarlo
    aparte, nunca aparecerían en la bandeja y un aviso dirigido a una sesión
    muerta se perdería para siempre.
    """
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")
    client.post(
        f"{V1}/messages/{enviado['id']}/claim",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )
    # Victor se va sin recoger su aviso.
    client.delete(f"{V1}/sessions/{victor['session_key']}", headers=mundo.auth("victor"))

    en_bandeja = _unclaimed(client, mundo, "pablo", pablo)

    assert any(m["from"] == SERVICE_ADDRESS for m in en_bandeja), (
        "el aviso del servicio debe ser visible para quien pueda atenderlo"
    )


# --------------------------------------------------------------------- descarte


def test_descartar_lo_oculta_solo_para_quien_descarta(client: TestClient, mundo: Mundo) -> None:
    """Prueba crítica de §11: A descarta, B lo sigue viendo."""
    victor = _registrar(client, mundo, "victor", "db")
    a = _registrar(client, mundo, "pablo", "general")
    b = _registrar(client, mundo, "pablo", "backend")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    client.post(
        f"{V1}/messages/{enviado['id']}/dismiss",
        headers=mundo.sesion("pablo", a["session_key"]),
    )

    assert _unclaimed(client, mundo, "pablo", a) == []
    assert [m["id"] for m in _unclaimed(client, mundo, "pablo", b)] == [enviado["id"]]


def test_descartar_es_idempotente(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)
    cabeceras = mundo.sesion("pablo", pablo["session_key"])

    primera = client.post(f"{V1}/messages/{enviado['id']}/dismiss", headers=cabeceras)
    segunda = client.post(f"{V1}/messages/{enviado['id']}/dismiss", headers=cabeceras)

    assert primera.status_code == segunda.status_code == 200


def test_descartar_no_cambia_el_estado_del_mensaje(client: TestClient, mundo: Mundo) -> None:
    """Descartar es una opinión de esa sesión, no un hecho sobre el mensaje."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to=None)

    client.post(
        f"{V1}/messages/{enviado['id']}/dismiss",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    with SessionLocal() as db:
        message = db.get(Message, enviado["id"])
        assert message is not None
        assert message.status == "unclaimed"
        assert message.claimed_by_session_id is None


# ------------------------------------------------- reclamo concurrente por HTTP


def test_ocho_sesiones_reclaman_por_http_y_gana_una(client: TestClient, mundo: Mundo) -> None:
    """La misma carrera del paso 5, pero por el endpoint real de claim."""
    victor = _registrar(client, mundo, "victor", "db")
    enviado = _enviar(client, mundo, "victor", victor, to=None)
    sesiones = [_registrar(client, mundo, "pablo", f"rol-{i}")["session_key"] for i in range(8)]

    codigos: list[int] = []
    candado = threading.Lock()
    barrera = threading.Barrier(len(sesiones))

    def competir(session_key: str) -> None:
        barrera.wait()
        respuesta = client.post(
            f"{V1}/messages/{enviado['id']}/claim",
            headers={
                "Authorization": f"Bearer {mundo.tokens['pablo']}",
                "X-Mesh-Session": session_key,
            },
        )
        with candado:
            codigos.append(respuesta.status_code)

    hilos = [threading.Thread(target=competir, args=(k,)) for k in sesiones]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert all(not h.is_alive() for h in hilos), "algún hilo se quedó colgado"
    assert codigos.count(200) == 1, f"ganaron {codigos.count(200)}: {codigos}"
    assert codigos.count(409) == len(sesiones) - 1

    with SessionLocal() as db:
        message = db.get(Message, enviado["id"])
        assert message is not None
        assert message.claimed_by_session_id is not None
        ganadora = db.get(AgentSession, message.claimed_by_session_id)
        assert ganadora is not None
