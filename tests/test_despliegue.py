"""M8: comprobaciones de la configuración de despliegue (SPEC §4 y §9).

Estas pruebas leen los archivos de infraestructura en vez de la aplicación. Son
las que evitan que un cambio "inocente" en `compose.yaml` abra el servicio a la
LAN o rompa la compatibilidad con Podman, cosas que ninguna prueba de la API
detectaría.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE_TEXTO = (RAIZ / "compose.yaml").read_text()
# Se parsea el YAML en vez de buscar cadenas: los comentarios del archivo
# mencionan justamente lo que NO se debe usar ("sin depends_on: condition",
# 'publicar "8000:8000" lo expondría a la LAN'), así que un `in` sobre el texto
# da falsos positivos. Es una lección de la primera versión de estas pruebas.
COMPOSE: dict[str, Any] = yaml.safe_load(COMPOSE_TEXTO)
SERVICIO: dict[str, Any] = COMPOSE["services"]["mesh"]
DOCKERFILE = (RAIZ / "Dockerfile").read_text()
EJEMPLO_ENV = (RAIZ / ".env.example").read_text()
GITIGNORE = (RAIZ / ".gitignore").read_text()


# ------------------------------------------------------ el túnel es la puerta


def test_el_puerto_no_se_publica_a_la_lan() -> None:
    """SPEC §9: el túnel de Cloudflare debe ser el ÚNICO camino de entrada.

    El panel se protege con usuario y contraseña propios, y eso *reemplaza* a
    Cloudflare Access. Es aceptable solo mientras nadie pueda llegar al
    contenedor por otra vía.
    """
    publicados = SERVICIO["ports"]

    assert publicados == ["127.0.0.1:8000:8000"], publicados
    for mapeo in publicados:
        host = mapeo.rsplit(":", 2)[0]
        assert host == "127.0.0.1", f"'{mapeo}' escucha fuera de loopback"


# --------------------------------------------------------- compatible con Podman


def test_no_usa_features_exclusivas_de_docker() -> None:
    """SPEC §4: evitar `depends_on: condition` y bind-mounts con permisos raros."""
    assert "depends_on" not in SERVICIO
    for nombre, definicion in COMPOSE["services"].items():
        assert "depends_on" not in definicion, nombre


def test_los_datos_van_en_un_volumen_nombrado() -> None:
    """Un bind-mount al host trae problemas de permisos en Podman rootless."""
    volumenes = SERVICIO["volumes"]

    assert volumenes == ["mesh-data:/data"], volumenes
    assert "mesh-data" in COMPOSE["volumes"], "debe declararse como volumen nombrado"
    for montaje in volumenes:
        origen = montaje.split(":", 1)[0]
        assert not origen.startswith((".", "/")), f"'{montaje}' es un bind-mount"


def test_el_contenedor_no_corre_como_root() -> None:
    assert "USER mesh" in DOCKERFILE


def test_el_dueño_de_data_se_fija_antes_del_volumen() -> None:
    """Así el volumen nombrado hereda los permisos al inicializarse.

    La alternativa —un `chown` en runtime— rompe con Podman rootless.
    """
    assert "chown -R mesh:mesh /data" in DOCKERFILE
    assert DOCKERFILE.index("chown -R mesh:mesh /data") < DOCKERFILE.index("USER mesh")


def test_las_migraciones_corren_antes_de_servir() -> None:
    assert "alembic upgrade head" in DOCKERFILE


# ----------------------------------------------------- los dos dominios (regla 6)


def test_los_dos_dominios_estan_documentados_como_independientes() -> None:
    assert "ADMIN_EMAIL_DOMAIN" in EJEMPLO_ENV
    assert "PUBLIC_SERVICE_DOMAIN" in EJEMPLO_ENV
    assert "INDEPENDIENTES" in EJEMPLO_ENV


def test_el_ejemplo_de_env_trae_dominios_distintos() -> None:
    """Si el ejemplo los pusiera iguales, alguien copiaría esa confusión."""
    valores = dict(
        linea.split("=", 1)
        for linea in EJEMPLO_ENV.splitlines()
        if "=" in linea and not linea.startswith("#")
    )

    assert valores["ADMIN_EMAIL_DOMAIN"] != valores["PUBLIC_SERVICE_DOMAIN"]


@pytest.mark.parametrize(
    "variable",
    [
        "ADMIN_EMAIL_DOMAIN",
        "PUBLIC_SERVICE_DOMAIN",
        "DATABASE_URL",
        "BOOTSTRAP_ADMIN_EMAIL",
        "LONGPOLL_MAX_SECONDS",
        "SESSION_STALE_AFTER_SECONDS",
        "LOG_LEVEL",
    ],
)
def test_estan_las_siete_variables_de_spec_4_1(variable: str) -> None:
    assert f"{variable}=" in EJEMPLO_ENV


# ------------------------------------------------------------------- secretos


def test_el_env_real_no_se_versiona() -> None:
    assert "\n.env\n" in GITIGNORE


def test_el_estado_del_cliente_no_se_versiona() -> None:
    """`.agent-mesh/session.json` lleva la session_key."""
    assert ".agent-mesh/" in GITIGNORE


def test_la_base_de_datos_no_se_versiona() -> None:
    assert "*.db" in GITIGNORE
