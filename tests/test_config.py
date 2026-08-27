"""M1: los dos dominios son independientes (CLAUDE.md, regla 6).

Esta prueba existe porque mezclar `ADMIN_EMAIL_DOMAIN` con
`PUBLIC_SERVICE_DOMAIN` ya está señalado como riesgo en el spec. Si alguien
deriva uno del otro "por conveniencia", esto lo atrapa.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides: str) -> Settings:
    base = {
        "admin_email_domain": "empresa-interna.test",
        "public_service_domain": "mesh.otrodominio.test",
        "bootstrap_admin_email": "admin@empresa-interna.test",
        "database_url": "sqlite:///./x.db",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_los_dos_dominios_no_se_derivan_uno_del_otro() -> None:
    settings = _settings()

    assert settings.admin_email_domain == "empresa-interna.test"
    assert settings.public_service_domain == "mesh.otrodominio.test"
    assert settings.admin_email_domain != settings.public_service_domain


def test_cambiar_el_dominio_publico_no_toca_el_del_panel() -> None:
    settings = _settings(public_service_domain="otro.example")

    assert settings.public_service_domain == "otro.example"
    assert settings.admin_email_domain == "empresa-interna.test"


def test_admin_de_bootstrap_debe_estar_en_el_dominio_del_panel() -> None:
    with pytest.raises(ValidationError, match="ADMIN_EMAIL_DOMAIN"):
        _settings(bootstrap_admin_email="admin@mesh.otrodominio.test")


def test_admin_de_bootstrap_valido_pasa() -> None:
    settings = _settings(bootstrap_admin_email="otro@empresa-interna.test")

    assert settings.bootstrap_admin_email == "otro@empresa-interna.test"
