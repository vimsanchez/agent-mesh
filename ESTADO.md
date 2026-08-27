# Estado del proyecto

Este archivo existe para que el contexto **viaje entre máquinas**. Lo demás vive en
`~/.claude/`, que es local y no cruza; esto sí está versionado.

Si acabas de clonar el repo en otra máquina, lee esto primero.

**Última actualización:** 2026-08-27 (tras PR #10)

---

## Dónde está el proyecto

Los **ocho pasos** del orden de implementación de `SPEC.md` §10 están implementados, y
las **siete pruebas críticas** del §11 pasan.

```
pytest        272 passed
ruff / format limpio
mypy strict   sin fallos en app/ (38 archivos)
rutas de API  17, exactamente las del §8
```

La skill de `skill/agent-mesh/` funciona contra el servicio **sin una sola
modificación**. Es el test de aceptación, no un artefacto que se ajuste al servicio.

### Todo el código está en `main` (desde PR #10)

Los ocho pasos se desarrollaron en PRs **apilados** (`#1 paso-1` ← `#2 paso-2` ← … ←
`#8 paso-8`) y se fusionaron **de arriba hacia abajo**: #1 entró a `main` primero, cuando
`paso-1` aún era solo el esqueleto, y cada PR siguiente cayó en la rama de abajo *antes*
de que esa rama recibiera su propio merge. Resultado: `main` quedó con el paso 1 y la
única punta que contenía los ocho pasos era `paso-7-documentos` (merge del #8).

Se corrigió con **PR #10** (`paso-7-documentos` → `main`, sin conflictos, 272 pruebas en
verde sobre el árbol fusionado). Desde ese merge, **`main` es la referencia**; las ramas
`paso-*` son historia y no contienen nada que falte en `main`.

Lección para la próxima pila: mergear **de abajo hacia arriba** (#8 → #7 → … → #1) o,
si ya se fusionó al revés, abrir un PR desde la rama que recibió el último merge.

---

## Pendiente de decisión

Tres cosas abiertas que **no están registradas en el código**.

### 1. `admin_users.role` con valores `owner | admin`

`SPEC.md` §9 pide que la tabla y el campo existan desde el día uno pero no fija los
valores. Los elegí al implementar el paso 2 y quedó sin confirmar. Nadie lee ese campo
todavía, así que cambiarlo sigue siendo barato.

### 2. Un hueco en `SKILL.md`, no en el servicio

La skill registra la sesión en su **paso 4** y consulta el `roster` en el **paso 6**. O
sea que el agente **no puede ver quién está conectado antes de elegir su rol**, aunque
el mismo documento le pida *"asegúrate de no repetir su rol"*.

Eso hace más probable que dos sesiones acaben con la misma dirección
(`victor.general` × 2). Se arregla reordenando los pasos de la skill.

Importa por dos motivos:

- Es la razón principal por la que el inbox pasa por el reclamo atómico. Corregir la
  skill no elimina esa necesidad —hay otros caminos al duplicado, como una sesión
  huérfana que aún no caduca— pero baja mucho la frecuencia.
- La skill no se ha tocado en todo el proyecto, a propósito. Modificarla es una
  decisión, no algo que hacer de paso.

### 3. El túnel de Cloudflare no está montado

El servicio publica en `127.0.0.1:8000` y está verificado que **no** responde en la IP
de LAN, como exige `SPEC.md` §9. Pero apuntar el túnel sigue pendiente, así que el
panel no es accesible desde fuera de la máquina.

Recordatorio del §9: el panel se protege con usuario y contraseña propios, y eso
*reemplaza* a Cloudflare Access. Eso solo es aceptable mientras el túnel sea la única
puerta. `tests/test_despliegue.py` verifica la parte del compose; el túnel en sí no lo
puede comprobar una prueba.

---

## Notas operativas

Cosas que muerden en una máquina nueva y no se deducen leyendo el código.

### El nombre del repo no coincide con el del directorio

- Repo remoto: **`vimsanchez/agent-mesh`** (privado)
- Directorio local en la máquina original: `~/git/agents_mesh`

Es deliberado: `agent-mesh` coincide con el nombre del producto en `SPEC.md` y con el
nombre de la skill. No "corregir" ninguno de los dos por parecer un descuido.

### `origin` va por HTTPS, no por SSH

`gh` está configurado con `git_protocol: ssh` para github.com, pero si
`~/.ssh/known_hosts` no tiene entrada para github.com, cualquier push por SSH falla con
`Host key verification failed`. En la máquina original se resolvió apuntando `origin` a
HTTPS, donde ya había credencial guardada.

Si prefieres SSH, los tres fingerprints publicados por GitHub coinciden con los que
devuelve `ssh-keyscan`, así que esto es seguro:

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
git remote set-url origin git@github.com:vimsanchez/agent-mesh.git
```

Falta confirmar que la clave pública de la máquina esté registrada en la cuenta.

### Python 3.12 con `uv`

`SPEC.md` pide 3.12. Si el Python del sistema es más viejo, `uv` lo resuelve sin tocarlo:

```bash
uv sync          # descarga cpython-3.12 y crea .venv
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

### `DATABASE_URL` es distinta en local y en contenedor

`.env.example` trae la ruta **local** (`sqlite:///./mesh.db`), que es la que necesitan
`alembic`, `uvicorn` y `pytest` fuera del contenedor. `compose.yaml` la sobrescribe con
`sqlite:////data/mesh.db`, que es el volumen nombrado.

Si `.env` trae la ruta del contenedor, cualquier comando local falla con
`unable to open database file`.

### Levantar y probar de punta a punta

```bash
cp .env.example .env      # ajusta ADMIN_EMAIL_DOMAIN y BOOTSTRAP_ADMIN_EMAIL
docker compose up -d --build
docker compose logs mesh | grep -A3 "ADMINISTRADOR INICIAL"   # la contraseña, una sola vez
```

Luego, con dos agentes en **directorios distintos** (`mesh.py` guarda su sesión en
`./.agent-mesh/` y dos sesiones en el mismo cwd se pisan):

```bash
export MESH_URL=http://127.0.0.1:8000 MESH_TOKEN=<token emitido en /admin>
cd /tmp/agente-a && python .../skill/agent-mesh/scripts/mesh.py register --project <slug> --role db
```

No redirijas la salida a `/dev/null` al verificar: un `send` desde el directorio
equivocado falla en silencio y parece un bug del servidor.
