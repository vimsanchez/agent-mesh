"""Configuración del servicio, leída del entorno del proceso.

Ningún secreto se lee de un archivo dentro del repo. En despliegue las variables
llegan por el entorno del contenedor; `.env` existe solo como comodidad local y
está en `.gitignore`.
"""

from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables de `SPEC.md` §4.1."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -----------------------------------------------------------------------
    # Dos dominios DISTINTOS e INDEPENDIENTES (CLAUDE.md, regla 6).
    # No derives uno del otro, no los mezcles, no asumas que coinciden.
    # Son campos separados a propósito y ninguno tiene default.
    # -----------------------------------------------------------------------

    admin_email_domain: str = Field(
        description="Dominio de correo obligatorio para usuarios del panel /admin.",
    )
    public_service_domain: str = Field(
        description="Dominio público del servicio. Sin relación con el anterior.",
    )

    database_url: str = "sqlite:///./mesh.db"
    bootstrap_admin_email: str

    # SPEC §4.1 no la lista, pero un panel protegido por cookie necesita firmar
    # esa cookie con algo. Si se deja vacía se genera una al azar en cada
    # arranque: seguro, pero cierra la sesión de los administradores en cada
    # reinicio. En despliegue conviene fijarla.
    secret_key: str = ""
    # Zona en la que el panel y las exportaciones MUESTRAN las fechas. No toca
    # lo que se guarda ni lo que responde la API, que son UTC siempre
    # (ver `services/timefmt.py`).
    display_timezone: str = "America/Mexico_City"
    longpoll_max_seconds: int = 30
    session_stale_after_seconds: int = 300
    log_level: str = "INFO"

    # C2 de SPEC-DELTA: a partir de cuántos mensajes un hilo sin resolver
    # provoca el hint de "escríbelo y marca resolve" en la respuesta del send.
    thread_long_hint_after: int = 10

    # C5 de SPEC-DELTA, fase 2, apagada por defecto: exigir que todo agreement
    # cite el documento donde quedó escrito. Se enciende solo si, con C1-C4 en
    # producción, los acuerdos siguen quedándose en los mensajes.
    require_agreement_doc: bool = False

    @field_validator("bootstrap_admin_email")
    @classmethod
    def _bootstrap_admin_uses_admin_domain(cls, value: str, info: ValidationInfo) -> str:
        """El admin de bootstrap obedece la regla del dominio del panel.

        Se valida contra `admin_email_domain` y NUNCA contra
        `public_service_domain`: son variables sin relación (CLAUDE.md, regla 6).
        """
        _, _, domain = value.partition("@")
        if not domain:
            msg = "BOOTSTRAP_ADMIN_EMAIL no parece un correo"
            raise ValueError(msg)
        expected = info.data.get("admin_email_domain")
        if expected and domain.lower() != str(expected).lower():
            msg = (
                f"BOOTSTRAP_ADMIN_EMAIL debe pertenecer a ADMIN_EMAIL_DOMAIN "
                f"({expected}), no a '{domain}'"
            )
            raise ValueError(msg)
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """Instancia única. `lru_cache` permite limpiarla en pruebas."""
    return Settings()  # type: ignore[call-arg]
