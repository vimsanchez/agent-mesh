"""M7: documentos por HTTP, con el conflicto optimista y el aislamiento."""

import threading

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import DocumentVersion
from app.db.session import SessionLocal
from tests.conftest import Mundo

V1 = "/api/v1"
RUTA = "20-contracts/api-orders.md"


def _registrar(
    client: TestClient, mundo: Mundo, persona: str, rol: str, slug: str = "proyecto-pablo"
) -> dict:
    respuesta = client.post(
        f"{V1}/sessions", headers=mundo.auth(persona), json={"project": slug, "role": rol}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _aportar(
    client: TestClient, mundo: Mundo, persona: str, sesion: dict, **cuerpo
) -> "object":
    payload = {
        "document_path": RUTA,
        "base_version": 0,
        "intent": "create",
        "rationale": "acordado en thr_8f2a",
        **cuerpo,
    }
    return client.post(
        f"{V1}/docs/contributions",
        headers=mundo.sesion(persona, sesion["session_key"]),
        json=payload,
    )


# ------------------------------------------------------------------- creación


def test_crear_un_documento(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = _aportar(
        client, mundo, "victor", victor, content="# API de pedidos\n\nPor cursor."
    )

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["current_version"] == 1
    assert datos["title"] == "API de pedidos", "el título sale del primer #"
    assert "Por cursor." in datos["content"]


def test_leer_devuelve_la_version_vigente(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc\n\n## Paginación\n\nOffset.")

    respuesta = client.get(
        f"{V1}/docs",
        params={"path": RUTA},
        headers=mundo.sesion("victor", victor["session_key"]),
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["current_version"] == 1


def test_leer_un_documento_inexistente_dice_como_crearlo(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = client.get(
        f"{V1}/docs",
        params={"path": "no/existe.md"},
        headers=mundo.sesion("victor", victor["session_key"]),
    )

    assert respuesta.status_code == 404
    assert "intent=create" in respuesta.json()["detail"]


def test_aportar_a_un_documento_inexistente_sin_create_falla(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = _aportar(client, mundo, "victor", victor, intent="append", content="X")

    assert respuesta.status_code == 404


def test_el_rationale_es_obligatorio(client: TestClient, mundo: Mundo) -> None:
    """Es lo que evita renegociar dentro de dos semanas algo ya acordado."""
    victor = _registrar(client, mundo, "victor", "db")

    respuesta = _aportar(client, mundo, "victor", victor, content="# X", rationale="  ")

    assert respuesta.status_code == 422
    assert "renegocie" in respuesta.json()["detail"]


# ------------------------------------------------------- conflicto optimista


def test_dos_aportaciones_con_la_misma_base_version_la_segunda_da_409(
    client: TestClient, mundo: Mundo
) -> None:
    """Prueba crítica de SPEC §11."""
    victor = _registrar(client, mundo, "victor", "db")
    pablo = _registrar(client, mundo, "pablo", "general")
    _aportar(
        client,
        mundo,
        "victor",
        victor,
        content="# Doc\n\n## Paginación\n\nOffset.",
    )

    primera = _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=1,
        intent="amend",
        anchor="## Paginación",
        content="Cursor.",
    )
    segunda = _aportar(
        client,
        mundo,
        "pablo",
        pablo,
        base_version=1,
        intent="amend",
        anchor="## Paginación",
        content="Keyset.",
    )

    assert primera.status_code == 200
    assert segunda.status_code == 409


def test_el_409_trae_la_version_vigente_y_su_contenido(
    client: TestClient, mundo: Mundo
) -> None:
    """`api.md` lo promete, y sin eso el agente solo puede reintentar a ciegas."""
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc\n\n## P\n\nOffset.")
    _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=1,
        intent="amend",
        anchor="## P",
        content="Cursor.",
    )

    conflicto = _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=1,
        intent="amend",
        anchor="## P",
        content="Keyset.",
    ).json()

    assert conflicto["current_version"] == 2
    assert "Cursor." in conflicto["content"]
    assert "No reintentes con la misma base_version" in conflicto["detail"]


def test_tras_releer_el_reintento_funciona(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc\n\n## P\n\nOffset.")
    _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=1,
        intent="amend",
        anchor="## P",
        content="Cursor.",
    )

    reintento = _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=2,
        intent="amend",
        anchor="## P",
        content="Keyset.",
    )

    assert reintento.status_code == 200
    assert reintento.json()["current_version"] == 3


def test_un_409_no_deja_basura_en_la_base(client: TestClient, mundo: Mundo) -> None:
    """El rollback importa: una versión a medias rompería el historial."""
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc\n\n## P\n\nOffset.")

    _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=99,
        intent="amend",
        anchor="## P",
        content="X.",
    )

    with SessionLocal() as db:
        versiones = list(db.scalars(select(DocumentVersion)))
    assert len(versiones) == 1


def test_crear_algo_que_ya_existe_con_base_version_0_da_409(
    client: TestClient, mundo: Mundo
) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc")

    respuesta = _aportar(client, mundo, "victor", victor, content="# Otro")

    assert respuesta.status_code == 409


# ----------------------------------------------------------------- historial


def test_el_historial_guarda_autor_intencion_y_motivo(client: TestClient, mundo: Mundo) -> None:
    victor = _registrar(client, mundo, "victor", "db")
    creado = _aportar(
        client,
        mundo,
        "victor",
        victor,
        content="# Doc\n\n## P\n\nOffset.",
        rationale="primera versión",
    ).json()
    _aportar(
        client,
        mundo,
        "victor",
        victor,
        base_version=1,
        intent="amend",
        anchor="## P",
        content="Cursor.",
        rationale="acordado con pablo.general",
    )

    historial = client.get(
        f"{V1}/docs/{creado['id']}/versions",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()

    assert [v["version"] for v in historial["versions"]] == [1, 2]
    assert [v["intent"] for v in historial["versions"]] == ["create", "amend"]
    assert historial["versions"][1]["rationale"] == "acordado con pablo.general"
    assert historial["versions"][1]["author_address"] == "victor.db"
    assert historial["path"] == RUTA


def test_el_autor_es_el_buzon_del_rol_no_la_direccion_precisa(
    client: TestClient, mundo: Mundo
) -> None:
    """El historial debe seguir siendo legible cuando esa sesión ya no exista, y
    el sufijo caduca con ella."""
    victor = _registrar(client, mundo, "victor", "db")
    creado = _aportar(client, mundo, "victor", victor, content="# Doc").json()

    historial = client.get(
        f"{V1}/docs/{creado['id']}/versions",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()

    assert historial["versions"][0]["author_address"] == "victor.db"


def test_el_historial_es_inmutable(client: TestClient, mundo: Mundo) -> None:
    """Cada aportación añade; ninguna reescribe lo anterior."""
    victor = _registrar(client, mundo, "victor", "db")
    creado = _aportar(
        client, mundo, "victor", victor, content="# Doc\n\n## P\n\nOffset."
    ).json()
    for i, texto in enumerate(("Cursor.", "Keyset.", "Cursor otra vez."), start=1):
        _aportar(
            client,
            mundo,
            "victor",
            victor,
            base_version=i,
            intent="amend",
            anchor="## P",
            content=texto,
        )

    historial = client.get(
        f"{V1}/docs/{creado['id']}/versions",
        headers=mundo.sesion("victor", victor["session_key"]),
    ).json()

    assert [v["version"] for v in historial["versions"]] == [1, 2, 3, 4]
    with SessionLocal() as db:
        primera = db.scalar(select(DocumentVersion).where(DocumentVersion.version == 1))
        assert primera is not None
        assert "Offset." in primera.content, "la versión 1 sigue intacta"


# ---------------------------------------------------------------- aislamiento


def test_el_indice_solo_lo_ve_un_miembro(client: TestClient, mundo: Mundo) -> None:
    """Prueba crítica de §11: un token de A no lee documentos de B."""
    respuesta = client.get(f"{V1}/projects/proyecto-luis/docs", headers=mundo.auth("pablo"))

    assert respuesta.status_code == 403
    assert "administrador" in respuesta.json()["detail"]


def test_un_documento_de_otro_proyecto_no_se_lee(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    _aportar(client, mundo, "victor", en_luis, content="# Secreto de Luis")

    respuesta = client.get(
        f"{V1}/docs",
        params={"path": RUTA},
        headers=mundo.sesion("victor", en_pablo["session_key"]),
    )

    assert respuesta.status_code == 404, "ni siquiera se confirma que existe"


def test_el_historial_de_otro_proyecto_no_se_ve(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")
    ajeno = _aportar(client, mundo, "victor", en_luis, content="# Secreto").json()

    respuesta = client.get(
        f"{V1}/docs/{ajeno['id']}/versions",
        headers=mundo.sesion("victor", en_pablo["session_key"]),
    )

    assert respuesta.status_code == 404


def test_la_misma_ruta_convive_en_dos_proyectos(client: TestClient, mundo: Mundo) -> None:
    en_luis = _registrar(client, mundo, "victor", "db", slug="proyecto-luis")
    en_pablo = _registrar(client, mundo, "victor", "backend")

    uno = _aportar(client, mundo, "victor", en_luis, content="# De Luis")
    otro = _aportar(client, mundo, "victor", en_pablo, content="# De Pablo")

    assert uno.status_code == otro.status_code == 200
    assert uno.json()["id"] != otro.json()["id"]


# ------------------------------------------------------- aportación concurrente


def test_aportaciones_concurrentes_solo_una_avanza_la_version(
    client: TestClient, mundo: Mundo
) -> None:
    """Ocho hilos con la misma base_version: exactamente uno debe ganar.

    Es el equivalente documental del reclamo atómico: si dos pasaran, una
    aportación se perdería en silencio.
    """
    victor = _registrar(client, mundo, "victor", "db")
    _aportar(client, mundo, "victor", victor, content="# Doc\n\n## P\n\nOffset.")
    sesiones = [_registrar(client, mundo, "pablo", f"rol-{i}")["session_key"] for i in range(8)]

    codigos: list[int] = []
    candado = threading.Lock()
    barrera = threading.Barrier(len(sesiones))

    def competir(session_key: str, texto: str) -> None:
        barrera.wait()
        respuesta = client.post(
            f"{V1}/docs/contributions",
            headers={
                "Authorization": f"Bearer {mundo.tokens['pablo']}",
                "X-Mesh-Session": session_key,
            },
            json={
                "document_path": RUTA,
                "base_version": 1,
                "intent": "amend",
                "anchor": "## P",
                "content": texto,
                "rationale": "carrera",
            },
        )
        with candado:
            codigos.append(respuesta.status_code)

    hilos = [
        threading.Thread(target=competir, args=(k, f"texto-{i}"))
        for i, k in enumerate(sesiones)
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    assert all(not h.is_alive() for h in hilos), "algún hilo se quedó colgado"
    assert codigos.count(200) == 1, f"pasaron {codigos.count(200)}: {codigos}"
    # Los perdedores deben recibir el 409 documentado, no un error del motor por
    # chocar con el constraint único.
    assert codigos.count(409) == len(sesiones) - 1, f"códigos: {sorted(codigos)}"
    assert 500 not in codigos

    with SessionLocal() as db:
        versiones = sorted(v.version for v in db.scalars(select(DocumentVersion)))
    assert versiones == [1, 2], f"no debe haber huecos ni saltos: {versiones}"
