# CLAUDE.md — Agent Mesh

## Qué es esto

Un servicio de mensajería asíncrona y conocimiento compartido **entre sesiones de agentes
de codificación** que pertenecen a personas distintas, con cuentas distintas, en máquinas
distintas, trabajando sobre el mismo proyecto.

Hoy los humanos hacen de mensajeros: un agente escribe un `.md`, la persona se lo pasa a
otra persona por Telegram, y esa se lo da a su agente. Este servicio elimina ese acarreo.

**Lee `SPEC.md` completo antes de escribir código.** Este archivo solo contiene las reglas
de trabajo; el diseño está allá.

## Stack

- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy 2.x (ORM) + Alembic
- SQLite en la primera etapa, con ruta de migración a Postgres
- Argon2id para contraseñas (`argon2-cffi`)
- Jinja2 para el panel de administración (server-rendered, sin framework de frontend)
- pytest para pruebas
- Docker Compose, compatible con Podman

## Reglas no negociables

1. **Nada de LLMs dentro del servicio.** Es un enrutador determinista. La inteligencia
   vive en los agentes, en los extremos. Si te dan ganas de añadir una llamada a un modelo
   para resolver ambigüedad, no lo hagas: pregunta.

2. **El proyecto es una frontera dura.** Ninguna consulta puede devolver datos de un
   proyecto al que el token no pertenece. Ni mensajes, ni roster, ni documentos, ni
   metadatos. Esto se prueba explícitamente.

3. **Nunca SQL específico de SQLite.** Todo pasa por el ORM. Migrar a Postgres debe ser
   cambiar `DATABASE_URL`, no reescribir. Sin `PRAGMA` fuera de la configuración de arranque,
   sin `rowid`, sin funciones propias del motor.

4. **El reclamo de mensajes debe ser atómico de verdad.** `UPDATE … WHERE claimed_by IS NULL`
   verificando `rowcount` dentro de transacción. No leas-luego-escribas. Hay una prueba con
   hilos reales concurrentes que debe pasar.

5. **Los documentos nunca se sobrescriben a ciegas.** Toda escritura es una *aportación*
   con `base_version`. Si la versión no coincide → `409 Conflict` con la versión actual.
   Se guarda la versión completa resultante, y el historial es inmutable.

6. **Dos dominios distintos, dos variables distintas.** `ADMIN_EMAIL_DOMAIN` (correos
   permitidos en el panel) y `PUBLIC_SERVICE_DOMAIN` (dominio público del servicio) **no
   tienen ninguna relación**. No derives una de la otra, no las mezcles, no asumas que
   coinciden. Este error ya está señalado como riesgo.

7. **Contraseñas siempre con hash Argon2id.** Jamás texto plano, jamás en logs, jamás en
   respuestas de la API. La contraseña de bootstrap se imprime una sola vez en el log de
   arranque y se marca `must_change_password`.

8. **Estructura completa, implementación mínima.** Todas las tablas de `SPEC.md` §7
   existen desde el primer commit, aunque algunas funciones no estén construidas todavía.
   Esto evita migraciones dolorosas después.

9. **La API de agentes no crea proyectos ni membresías.** `GET /projects` es de solo
   lectura y solo devuelve los proyectos de la persona dueña del token. Nada de
   `POST /projects`, nada de auto-inscripción, ni siquiera "por conveniencia en
   desarrollo". Eso vive únicamente en el panel de administración. Ver `SPEC.md` §3.1.

10. **Los mensajes de error de registro deben ser accionables.** Un `403` en
    `POST /sessions` trae un `detail` que le dice al agente qué hacer —
    *"pídele a tu administrador que agregue a tu persona a este proyecto"*— y no un
    `"forbidden"` seco. Un agente con un error vago improvisa; uno con instrucción se
    detiene.

## Convenciones de código

- Tipado estricto en todo lo público. `mypy` en modo `strict` sobre `app/`.
- Ruff para lint y formato.
- Estructura:
  ```
  app/
    main.py            # Composición de la app
    config.py          # Settings vía pydantic-settings
    db/                # Engine, sesión, modelos
    api/v1/            # Endpoints de agentes
    admin/             # Panel: rutas + plantillas Jinja
    services/          # Lógica de dominio (mensajería, conocimiento, identidad)
    security/          # Tokens, hashing, dependencias de auth
  migrations/          # Alembic
  tests/
  ```
- La lógica de dominio vive en `services/`, no en los handlers. Los handlers solo validan,
  llaman y serializan.
- Errores de dominio como excepciones propias, traducidas a HTTP en un solo lugar.

## Cómo trabajar

- **Sigue el orden de implementación de `SPEC.md` §10.** No saltes adelante.
- Un commit por paso de ese orden, con las pruebas del paso incluidas.
- Antes de dar por terminado un paso, corre `pytest`, `ruff check` y `mypy`.
- Si algo del spec es ambiguo o contradictorio, **pregunta antes de decidir**. No inventes
  comportamiento y sigas adelante.
- Si encuentras que una decisión del spec no funciona en la práctica, dilo con el motivo
  concreto. El spec es un punto de partida bien pensado, no un dogma.

## Lo que está explícitamente fuera de alcance

No implementes nada de esto, ni siquiera "por si acaso":

- Bots de Telegram o cualquier otro transporte externo.
- Comunicación entre proyectos distintos.
- Cualquier orquestación con modelos de lenguaje.
- WebSocket o SSE en la primera etapa (long polling basta; el modelo de datos ya lo
  permite después sin cambios).
- Un frontend con React/Vue/Svelte para el panel.
- La skill del lado del agente. Se diseña después, en documento aparte, una vez que la API
  esté estable.

## Contexto sobre los usuarios

Las personas que van a usar esto son desarrolladores con sus propias sesiones de Claude
Code. Algunos separan tareas en varios agentes por rol (backend, base de datos), otros usan
un solo agente que hace de todo y registra el rol `general`. **El sistema debe funcionar
igual de bien en ambos casos.** El rol es una etiqueta de dirección, no un contrato de
responsabilidades.
