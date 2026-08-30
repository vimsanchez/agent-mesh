"""M5: envío, inbox con long polling, ack, progress e hilos."""

import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.conftest import Mundo

V1 = "/api/v1"
SETTINGS = get_settings()


def _registrar(
    client: TestClient, mundo: Mundo, persona: str, rol: str, slug: str = "proyecto-pablo"
) -> dict:
    respuesta = client.post(
        f"{V1}/sessions", headers=mundo.auth(persona), json={"project": slug, "role": rol}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _enviar(client: TestClient, mundo: Mundo, persona: str, sesion: dict, **cuerpo) -> dict:
    payload = {"subject": "Contrato de /v1/orders", "body": "…", **cuerpo}
    respuesta = client.post(
        f"{V1}/messages", headers=mundo.sesion(persona, sesion["session_key"]), json=payload
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _inbox(
    client: TestClient, mundo: Mundo, persona: str, sesion: dict, wait: int = 0
) -> list[dict]:
    respuesta = client.get(
        f"{V1}/inbox?wait={wait}", headers=mundo.sesion(persona, sesion["session_key"])
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["messages"]


# ------------------------------------------------------------------------ envío


def test_enviar_crea_hilo_nuevo(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    enviado = _enviar(client, mundo, "victor", victor, to="pablo.general")

    assert enviado["id"].startswith("msg_")
    assert enviado["thread_id"].startswith("thr_")
    assert enviado["status"] == "pending"


def test_enviar_sin_sesion_no_se_permite(client: TestClient, mundo: Mundo) -> None:
    """El remitente sale de la sesión, no del token: sin sesión no hay dirección."""
    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.auth("victor"),
        json={"to": "pablo.general", "subject": "x", "body": "y"},
    )

    assert respuesta.status_code == 401
    assert "regístrate primero" in respuesta.json()["detail"]


def test_escribirle_a_un_rol_que_nadie_levanto_no_falla(
    client: TestClient, mundo: Mundo
) -> None:
    """SPEC §5.2: el mensaje espera. No asumas que falló."""
    victor = _registrar(client, mundo, "victor", "db")

    enviado = _enviar(client, mundo, "victor", victor, to="pablo.db")

    assert enviado["status"] == "pending", "espera, no se rechaza ni se descarta"


def test_sin_destinatario_nace_en_no_reclamados(client: TestClient, mundo: Mundo) -> None:
    """SPEC §5.1: `to` nulo -> nace directamente en la bandeja."""
    victor = _registrar(client, mundo, "victor", "db")

    enviado = _enviar(client, mundo, "victor", victor, to=None)

    assert enviado["status"] == "unclaimed"


@pytest.mark.parametrize("direccion_mala", ["pablo", "pablo..general", "", "a.b.c.d"])
def test_una_direccion_mal_formada_se_rechaza(
    client: TestClient, mundo: Mundo, direccion_mala: str
) -> None:
    """Un rol inexistente espera; una dirección basura no la levantará nadie."""
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", victor["session_key"]),
        json={"to": direccion_mala, "subject": "x", "body": "y"},
    )

    assert respuesta.status_code == 422


def test_un_asunto_vacio_se_rechaza(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", victor["session_key"]),
        json={"to": "pablo.general", "subject": "   ", "body": "y"},
    )

    assert respuesta.status_code == 422


def test_los_cinco_kinds_se_aceptan(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    for kind in ("question", "answer", "notice", "proposal", "agreement"):
        enviado = _enviar(client, mundo, "victor", victor, to="pablo.general", kind=kind)
        assert enviado["id"]


def test_un_kind_inventado_se_rechaza(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", victor["session_key"]),
        json={"to": "pablo.general", "kind": "chisme", "subject": "x", "body": "y"},
    )

    assert respuesta.status_code == 422


# ------------------------------------------------------------------------ hilos


def test_reply_to_hereda_el_hilo(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general")

    respuesta = _enviar(
        client,
        mundo,
        "pablo",
        pablo,
        to="victor.db",
        kind="answer",
        in_reply_to=pregunta["id"],
    )

    assert respuesta["thread_id"] == pregunta["thread_id"]


def test_el_hilo_sale_en_orden_cronologico(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general", subject="P1")
    _enviar(
        client,
        mundo,
        "pablo",
        pablo,
        to="victor.db",
        kind="answer",
        subject="R1",
        in_reply_to=pregunta["id"],
    )

    hilo = client.get(
        f"{V1}/threads/{pregunta['thread_id']}",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()

    assert [m["subject"] for m in hilo["messages"]] == ["P1", "R1"]
    assert hilo["messages"][0]["from"] == "victor.db"
    assert hilo["messages"][1]["from"] == "pablo.general"


def test_un_hilo_de_otro_proyecto_no_se_ve(client: TestClient, mundo: Mundo) -> None:
    """Aislamiento: victor está en ambos proyectos, pero los hilos no cruzan."""
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    ajeno = _enviar(client, mundo, "victor", en_luis, to="luis.db")

    respuesta = client.get(
        f"{V1}/threads/{ajeno['thread_id']}",
        headers=mundo.sesion("victor", en_pablo["session_key"]),
    )

    assert respuesta.status_code == 404


def test_un_reply_to_de_otro_proyecto_se_rechaza(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    ajeno = _enviar(client, mundo, "victor", en_luis, to="luis.db")

    respuesta = client.post(
        f"{V1}/messages",
        headers=mundo.sesion("victor", en_pablo["session_key"]),
        json={"to": "pablo.general", "subject": "x", "body": "y", "in_reply_to": ajeno["id"]},
    )

    assert respuesta.status_code == 404


# ------------------------------------------------------------------------ inbox


def test_el_inbox_entrega_lo_dirigido_a_esta_sesion(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general", subject="Para Pablo")

    recibidos = _inbox(client, mundo, "pablo", pablo)

    assert [m["subject"] for m in recibidos] == ["Para Pablo"]
    assert recibidos[0]["from"] == "victor.db"
    assert recibidos[0]["status"] == "delivered"


def test_el_inbox_no_entrega_lo_de_otra_direccion(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.db")

    assert _inbox(client, mundo, "pablo", pablo) == []


def test_el_inbox_vacio_no_es_un_error(client: TestClient, mundo: Mundo) -> None:
    """SPEC §5.4: lista vacía = nada nuevo ahora. Nada más."""
    pablo = _registrar(client, mundo, "pablo", "general")

    assert _inbox(client, mundo, "pablo", pablo) == []


def test_una_direccion_precisa_llega_solo_a_esa_sesion(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    una = _registrar(client, mundo, "pablo", "general")
    otra = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to=una["session_address"])

    assert len(_inbox(client, mundo, "pablo", una)) == 1
    assert _inbox(client, mundo, "pablo", otra) == []


def test_dos_sesiones_del_mismo_buzon_no_reciben_las_dos(
    client: TestClient, mundo: Mundo
) -> None:
    """El caso que motivó el reclamo en el inbox.

    Si ambas recibieran el mensaje, las dos contestarían la misma pregunta y el
    remitente tendría dos respuestas posiblemente contradictorias.
    """
    victor = _registrar(client, mundo, "victor", "db")
    una = _registrar(client, mundo, "pablo", "general")
    otra = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")

    primera = _inbox(client, mundo, "pablo", una)
    segunda = _inbox(client, mundo, "pablo", otra)

    assert len(primera) + len(segunda) == 1, "exactamente una se lo lleva"


def test_el_inbox_reentrega_al_dueño_hasta_que_confirma(
    client: TestClient, mundo: Mundo
) -> None:
    """Salva al agente que recibió el mensaje y murió antes de hacer ack."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")

    primera = _inbox(client, mundo, "pablo", pablo)
    segunda = _inbox(client, mundo, "pablo", pablo)

    assert len(primera) == 1
    assert len(segunda) == 1, "sin ack, sigue apareciendo para su dueño"


def test_tras_el_ack_ya_no_se_reentrega(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")
    recibido = _inbox(client, mundo, "pablo", pablo)[0]

    client.post(
        f"{V1}/messages/{recibido['id']}/ack",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    assert _inbox(client, mundo, "pablo", pablo) == []


# --------------------------------------------------------------- ack y progress


def test_ack_es_idempotente(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")
    recibido = _inbox(client, mundo, "pablo", pablo)[0]
    cabeceras = mundo.sesion("pablo", pablo["session_key"])

    primera = client.post(f"{V1}/messages/{recibido['id']}/ack", headers=cabeceras)
    segunda = client.post(f"{V1}/messages/{recibido['id']}/ack", headers=cabeceras)

    assert primera.status_code == segunda.status_code == 200


def test_no_se_puede_confirmar_algo_que_no_te_entregaron(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.general")

    respuesta = client.post(
        f"{V1}/messages/{enviado['id']}/ack",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    assert respuesta.status_code == 404


def test_progress_marca_en_proceso(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")
    recibido = _inbox(client, mundo, "pablo", pablo)[0]

    respuesta = client.post(
        f"{V1}/messages/{recibido['id']}/progress",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    assert respuesta.json()["status"] == "in_progress"


def test_no_se_puede_marcar_progreso_de_un_mensaje_ajeno(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")
    recibido = _inbox(client, mundo, "pablo", pablo)[0]

    respuesta = client.post(
        f"{V1}/messages/{recibido['id']}/progress",
        headers=mundo.sesion("victor", victor["session_key"]),
    )

    assert respuesta.status_code == 404


# -------------------------------------------------------- la regla de `answered`


def test_un_answer_cierra_la_pregunta(client: TestClient, mundo: Mundo) -> None:
    """La única vía por la que `answered` es alcanzable."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general")

    _enviar(
        client,
        mundo,
        "pablo",
        pablo,
        to="victor.db",
        kind="answer",
        in_reply_to=pregunta["id"],
    )

    hilo = client.get(
        f"{V1}/threads/{pregunta['thread_id']}",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()
    original = next(m for m in hilo["messages"] if m["id"] == pregunta["id"])
    assert original["status"] == "answered"


def test_una_repregunta_no_cierra_la_pregunta(client: TestClient, mundo: Mundo) -> None:
    """Pedir una aclaración no es responder."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general")

    _enviar(
        client,
        mundo,
        "pablo",
        pablo,
        to="victor.db",
        kind="question",
        subject="¿a qué te refieres?",
        in_reply_to=pregunta["id"],
    )

    hilo = client.get(
        f"{V1}/threads/{pregunta['thread_id']}",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()
    original = next(m for m in hilo["messages"] if m["id"] == pregunta["id"])
    assert original["status"] != "answered"


def test_un_answer_sin_reply_to_no_cierra_nada(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general")

    _enviar(client, mundo, "pablo", pablo, to="victor.db", kind="answer")

    hilo = client.get(
        f"{V1}/threads/{pregunta['thread_id']}",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()
    original = next(m for m in hilo["messages"] if m["id"] == pregunta["id"])
    assert original["status"] != "answered"


def test_un_mensaje_answered_ya_no_se_entrega(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    pregunta = _enviar(client, mundo, "victor", victor, to="pablo.general")
    _enviar(
        client,
        mundo,
        "pablo",
        pablo,
        to="victor.db",
        kind="answer",
        in_reply_to=pregunta["id"],
    )

    recibidos = _inbox(client, mundo, "pablo", pablo)

    assert pregunta["id"] not in [m["id"] for m in recibidos]


# ------------------------------------------------------------------ long polling


def test_el_long_poll_devuelve_temprano_si_ya_hay_algo(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _enviar(client, mundo, "victor", victor, to="pablo.general")

    inicio = time.perf_counter()
    recibidos = _inbox(client, mundo, "pablo", pablo, wait=10)
    transcurrido = time.perf_counter() - inicio

    assert len(recibidos) == 1
    assert transcurrido < 2, f"no debió esperar; tardó {transcurrido:.2f}s"


def test_el_long_poll_espera_y_devuelve_vacio_al_vencer(
    client: TestClient, mundo: Mundo
) -> None:
    """Vencer no es un error: es "no hay nada nuevo ahora"."""
    pablo = _registrar(client, mundo, "pablo", "general")

    inicio = time.perf_counter()
    recibidos = _inbox(client, mundo, "pablo", pablo, wait=2)
    transcurrido = time.perf_counter() - inicio

    assert recibidos == []
    assert transcurrido >= 1.5, f"debió esperar ~2s; tardó {transcurrido:.2f}s"


def test_el_wait_se_recorta_al_maximo_configurado(client: TestClient, mundo: Mundo) -> None:
    """`LONGPOLL_MAX_SECONDS` es el tope, no una sugerencia del cliente."""
    pablo = _registrar(client, mundo, "pablo", "general")

    inicio = time.perf_counter()
    _inbox(client, mundo, "pablo", pablo, wait=SETTINGS.longpoll_max_seconds + 600)
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < SETTINGS.longpoll_max_seconds + 3, (
        f"pidió {SETTINGS.longpoll_max_seconds + 600}s y esperó "
        f"{transcurrido:.1f}s; el tope debe mandar"
    )


# --------------------------------------------------------- delta v0.2: C1, ack


def test_ack_devuelve_la_llave_del_hilo(client: TestClient, mundo: Mundo) -> None:
    """C1: el ack trae thread_id, thread_status y subject (SPEC-DELTA).

    El momento del ack es cuando el mensaje desaparece del inbox; si la
    respuesta trae la llave, el agente que no apuntó nada la conserva.
    """
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(
        client, mundo, "victor", victor, to="pablo.general", subject="¿cursor u offset?"
    )
    recibido = _inbox(client, mundo, "pablo", pablo)[0]

    salida = client.post(
        f"{V1}/messages/{recibido['id']}/ack",
        headers=mundo.sesion("pablo", pablo["session_key"]),
    )

    assert salida.status_code == 200
    cuerpo = salida.json()
    assert cuerpo["acked"] is True
    assert cuerpo["thread_id"] == enviado["thread_id"]
    assert cuerpo["thread_status"] == "open"
    assert cuerpo["subject"] == "¿cursor u offset?"


# -------------------------------------------------------- delta v0.2: C2, send


def test_send_devuelve_estado_del_hilo_y_conteo(client: TestClient, mundo: Mundo) -> None:
    """C2: SentOut trae thread_status y thread_message_count siempre."""
    victor = _registrar(client, mundo, "victor", "db")

    primero = _enviar(client, mundo, "victor", victor, to="pablo.general")
    assert primero["thread_status"] == "open"
    assert primero["thread_message_count"] == 1
    assert primero["hint"] is None

    segundo = _enviar(
        client, mundo, "victor", victor, to="pablo.general", thread_id=primero["thread_id"]
    )
    assert segundo["thread_message_count"] == 2


def test_agreement_sin_cita_en_rationales_trae_hint(
    client: TestClient, mundo: Mundo
) -> None:
    """C2 caso 1: agreement cuyo hilo nadie citó al aportar -> hint no nulo."""
    victor = _registrar(client, mundo, "victor", "db")

    salida = _enviar(
        client, mundo, "victor", victor, to="pablo.general", kind="agreement"
    )

    assert salida["hint"] is not None
    assert salida["thread_id"] in salida["hint"]
    assert "20-contracts/" in salida["hint"]


def test_agreement_ya_citado_no_trae_hint(client: TestClient, mundo: Mundo) -> None:
    """C2 caso 1, negativo: un rationale que menciona el hilo silencia el hint."""
    victor = _registrar(client, mundo, "victor", "db")
    primero = _enviar(
        client, mundo, "victor", victor, to="pablo.general", kind="agreement"
    )

    aporte = client.post(
        f"{V1}/docs/contributions",
        headers=mundo.sesion("victor", victor["session_key"]),
        json={
            "document_path": "20-contracts/paginacion.md",
            "base_version": 0,
            "intent": "create",
            "content": "Cursor, no offset.",
            "rationale": f"Acordado en {primero['thread_id']}",
        },
    )
    assert aporte.status_code == 200, aporte.text

    segundo = _enviar(
        client,
        mundo,
        "victor",
        victor,
        to="pablo.general",
        kind="agreement",
        thread_id=primero["thread_id"],
    )
    assert segundo["hint"] is None


def test_hilo_largo_trae_hint(client: TestClient, mundo: Mundo) -> None:
    """C2 caso 2: superar THREAD_LONG_HINT_AFTER sin resolver -> hint de hilo largo."""
    victor = _registrar(client, mundo, "victor", "db")

    primero = _enviar(client, mundo, "victor", victor, to="pablo.general")
    ultimo = primero
    for _ in range(10):  # con el default 10, el mensaje 11 supera el umbral
        ultimo = _enviar(
            client, mundo, "victor", victor, to="pablo.general", thread_id=primero["thread_id"]
        )

    assert ultimo["thread_message_count"] == 11
    assert ultimo["hint"] is not None
    assert "resolve" in ultimo["hint"]


# ------------------------------------------------------- delta v0.2: C4, inbox


def test_inbox_vacio_no_trae_context(client: TestClient, mundo: Mundo) -> None:
    """C4: la respuesta vacía del long poll queda idéntica a hoy, para no meter
    ruido en el bucle del monitor."""
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = client.get(
        f"{V1}/inbox", headers=mundo.sesion("victor", victor["session_key"])
    )

    assert respuesta.json() == {"messages": []}


def test_inbox_con_mensajes_trae_context(client: TestClient, mundo: Mundo) -> None:
    """C4: con mensajes llega el bloque context con los hilos abiertos más viejos."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    enviado = _enviar(client, mundo, "victor", victor, to="pablo.general")

    cuerpo = client.get(
        f"{V1}/inbox", headers=mundo.sesion("pablo", pablo["session_key"])
    ).json()

    assert cuerpo["messages"]
    contexto = cuerpo["context"]
    assert contexto["open_threads"] == 1
    assert contexto["oldest_open"][0]["id"] == enviado["thread_id"]
    assert contexto["oldest_open"][0]["message_count"] == 1
