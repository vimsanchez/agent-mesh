"""M4: registro de sesiones, latido, cierre y roster."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db.base import utcnow
from app.db.models import AgentSession
from app.db.session import SessionLocal
from app.services import sessions as sessions_service
from tests.conftest import Mundo

V1 = "/api/v1"
SETTINGS = get_settings()


def _registrar(client: TestClient, mundo: Mundo, persona: str, slug: str, rol: str) -> dict:
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth(persona),
        json={"project": slug, "role": rol},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _envejecer(session_key: str, segundos: int) -> None:
    """Empuja `last_seen_at` al pasado para simular una sesión sin latido.

    Se manipula el reloj de la fila en vez de dormir: dormir 300 s en una prueba
    no es una opción, y lo que se quiere probar es la regla, no el reloj.
    """
    with SessionLocal() as db:
        agent_session = db.scalar(
            select(AgentSession).where(AgentSession.session_key == session_key)
        )
        assert agent_session is not None
        agent_session.last_seen_at = utcnow() - timedelta(seconds=segundos)
        db.commit()


# -------------------------------------------------------------------- registro


def test_registrar_devuelve_direccion_y_clave(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    assert datos["address"] == "victor.db"
    assert datos["project"] == "proyecto-pablo"
    assert datos["session_key"].startswith("ses_")


def test_el_rol_general_es_igual_de_valido(client: TestClient, mundo: Mundo) -> None:
    """Pablo trabaja con un solo agente que hace de todo (SPEC §3)."""
    datos = _registrar(client, mundo, "pablo", "proyecto-pablo", "general")

    assert datos["address"] == "pablo.general"


def test_el_rol_se_normaliza(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "  DB  ")

    assert datos["address"] == "victor.db"


def test_registrarse_en_un_proyecto_ajeno_da_403_accionable(
    client: TestClient, mundo: Mundo
) -> None:
    """Prueba crítica de §11."""
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth("pablo"),
        json={"project": "proyecto-luis", "role": "general"},
    )

    assert respuesta.status_code == 403
    assert "pídele a tu administrador" in respuesta.json()["detail"]


def test_registrarse_en_un_slug_inexistente_da_404(client: TestClient, mundo: Mundo) -> None:
    """Prueba crítica de §11."""
    respuesta = client.post(
        f"{V1}/sessions",
        headers=mundo.auth("victor"),
        json={"project": "proyecto-inventado", "role": "db"},
    )

    assert respuesta.status_code == 404


def test_dos_sesiones_de_la_misma_persona_con_roles_distintos(
    client: TestClient, mundo: Mundo
) -> None:
    """Mismo token, sesiones distintas. Es correcto y deseado (SPEC §3.2)."""
    backend = _registrar(client, mundo, "victor", "proyecto-pablo", "backend")
    base = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    assert backend["session_key"] != base["session_key"]
    assert {backend["address"], base["address"]} == {"victor.backend", "victor.db"}


def test_repetir_el_mismo_rol_no_es_error(client: TestClient, mundo: Mundo) -> None:
    """SPEC §3: si hay dos sesiones con la misma dirección, el mensaje se ofrece
    a ambas y decide el reclamo atómico. Así que registrar no debe rechazarlo."""
    una = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    otra = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    assert una["address"] == otra["address"] == "victor.db"
    assert una["session_key"] != otra["session_key"]


def test_la_misma_persona_puede_tener_sesiones_en_dos_proyectos(
    client: TestClient, mundo: Mundo
) -> None:
    en_pablo = _registrar(client, mundo, "victor", "proyecto-pablo", "backend")
    en_luis = _registrar(client, mundo, "victor", "proyecto-luis", "backend")

    assert en_pablo["address"] == en_luis["address"] == "victor.backend"
    assert en_pablo["project"] != en_luis["project"]


# ----------------------------------------------------------------------- latido


def test_el_latido_mantiene_viva_la_sesion(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    _envejecer(datos["session_key"], SETTINGS.session_stale_after_seconds - 10)

    respuesta = client.post(
        f"{V1}/sessions/{datos['session_key']}/heartbeat", headers=mundo.auth("victor")
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "active"


def test_no_se_puede_latir_la_sesion_de_otra_persona(client: TestClient, mundo: Mundo) -> None:
    """Sin esto, quien tuviera una session_key ajena mantendría viva otra sesión."""
    de_victor = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    respuesta = client.post(
        f"{V1}/sessions/{de_victor['session_key']}/heartbeat",
        headers=mundo.auth("pablo"),
    )

    assert respuesta.status_code == 404


def test_una_sesion_stale_no_revive_con_un_latido(client: TestClient, mundo: Mundo) -> None:
    """410 y a registrarse de nuevo, como dice la tabla de `api.md`.

    Revivirla dejaría en el aire los mensajes que ya volvieron a circular por su
    ausencia.
    """
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    _envejecer(datos["session_key"], SETTINGS.session_stale_after_seconds + 60)
    client.get(f"{V1}/projects/proyecto-pablo/roster", headers=mundo.auth("victor"))

    respuesta = client.post(
        f"{V1}/sessions/{datos['session_key']}/heartbeat", headers=mundo.auth("victor")
    )

    assert respuesta.status_code == 410
    assert "vuelve a registrarte" in respuesta.json()["detail"]


def test_latir_una_sesion_cerrada_da_410(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    client.delete(f"{V1}/sessions/{datos['session_key']}", headers=mundo.auth("victor"))

    respuesta = client.post(
        f"{V1}/sessions/{datos['session_key']}/heartbeat", headers=mundo.auth("victor")
    )

    assert respuesta.status_code == 410


# ------------------------------------------------------------------------ cierre


def test_cerrar_marca_la_sesion(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    respuesta = client.delete(
        f"{V1}/sessions/{datos['session_key']}", headers=mundo.auth("victor")
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"address": "victor.db", "status": "closed"}


def test_cerrar_dos_veces_no_es_error(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    client.delete(f"{V1}/sessions/{datos['session_key']}", headers=mundo.auth("victor"))

    segunda = client.delete(
        f"{V1}/sessions/{datos['session_key']}", headers=mundo.auth("victor")
    )

    assert segunda.status_code == 200


def test_no_se_puede_cerrar_la_sesion_de_otra_persona(client: TestClient, mundo: Mundo) -> None:
    de_victor = _registrar(client, mundo, "victor", "proyecto-pablo", "db")

    respuesta = client.delete(
        f"{V1}/sessions/{de_victor['session_key']}", headers=mundo.auth("pablo")
    )

    assert respuesta.status_code == 404


# ------------------------------------------------------------------------ roster


def test_el_roster_muestra_a_los_vivos_del_proyecto(client: TestClient, mundo: Mundo) -> None:
    _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    _registrar(client, mundo, "pablo", "proyecto-pablo", "general")

    datos = client.get(
        f"{V1}/projects/proyecto-pablo/roster", headers=mundo.auth("victor")
    ).json()

    assert {s["address"] for s in datos["sessions"]} == {"victor.db", "pablo.general"}


def test_el_roster_no_mezcla_proyectos(client: TestClient, mundo: Mundo) -> None:
    """Aislamiento: victor está en los dos proyectos, pero cada roster es suyo."""
    _registrar(client, mundo, "victor", "proyecto-pablo", "backend")
    _registrar(client, mundo, "luis", "proyecto-luis", "db")

    en_pablo = client.get(
        f"{V1}/projects/proyecto-pablo/roster", headers=mundo.auth("victor")
    ).json()

    assert {s["address"] for s in en_pablo["sessions"]} == {"victor.backend"}
    assert "luis.db" not in str(en_pablo)


def test_el_roster_deja_de_mostrar_a_quien_no_late(client: TestClient, mundo: Mundo) -> None:
    """El marcado de stale es perezoso: ocurre al leer el roster."""
    caida = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    _registrar(client, mundo, "pablo", "proyecto-pablo", "general")
    _envejecer(caida["session_key"], SETTINGS.session_stale_after_seconds + 60)

    datos = client.get(
        f"{V1}/projects/proyecto-pablo/roster", headers=mundo.auth("victor")
    ).json()

    assert {s["address"] for s in datos["sessions"]} == {"pablo.general"}


def test_el_roster_no_muestra_sesiones_cerradas(client: TestClient, mundo: Mundo) -> None:
    datos = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    client.delete(f"{V1}/sessions/{datos['session_key']}", headers=mundo.auth("victor"))

    roster = client.get(
        f"{V1}/projects/proyecto-pablo/roster", headers=mundo.auth("victor")
    ).json()

    assert roster["sessions"] == []


# --------------------------------------------------- expiración como función pura


def test_expire_devuelve_las_sesiones_que_acaba_de_marcar(
    client: TestClient, mundo: Mundo
) -> None:
    """El paso 5 usa ese valor de retorno para hacer circular sus mensajes."""
    caida = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    viva = _registrar(client, mundo, "pablo", "proyecto-pablo", "general")
    _envejecer(caida["session_key"], SETTINGS.session_stale_after_seconds + 60)

    with SessionLocal() as db:
        marcadas = sessions_service.expire_stale_sessions(db, SETTINGS)
        db.commit()

    claves = {s.session_key for s in marcadas}
    assert caida["session_key"] in claves
    assert viva["session_key"] not in claves


def test_expire_es_idempotente(client: TestClient, mundo: Mundo) -> None:
    caida = _registrar(client, mundo, "victor", "proyecto-pablo", "db")
    _envejecer(caida["session_key"], SETTINGS.session_stale_after_seconds + 60)

    with SessionLocal() as db:
        primera = sessions_service.expire_stale_sessions(db, SETTINGS)
        db.commit()
    with SessionLocal() as db:
        segunda = sessions_service.expire_stale_sessions(db, SETTINGS)
        db.commit()

    assert len(primera) == 1
    assert segunda == [], "no debe volver a marcar lo ya marcado"
