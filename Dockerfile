# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv fija las versiones con uv.lock, dentro y fuera del contenedor.
COPY --from=ghcr.io/astral-sh/uv:0.5.24 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

# Capa de dependencias, separada para que un cambio en el código no la invalide.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --frozen --no-dev

# Usuario sin privilegios. /data se crea con su dueño ANTES de declarar el
# volumen: así el volumen nombrado hereda esos permisos al inicializarse, y no
# hace falta chown en runtime (que rompería con Podman rootless).
RUN useradd --system --uid 10001 --create-home mesh \
    && mkdir -p /data \
    && chown -R mesh:mesh /data /srv
USER mesh

EXPOSE 8000

# Las migraciones corren antes de servir. Con SQLite en un solo contenedor no
# hay carrera posible entre réplicas.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
