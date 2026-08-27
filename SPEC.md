# Agent Mesh — Especificación de diseño

**Versión del documento:** 0.1 (borrador inicial)
**Autor:** Víctor (diseño conversado) — implementación delegada a Claude Code
**Estado:** listo para arrancar implementación

---

## 1. Problema

Dos o más personas trabajan en un mismo proyecto de software, cada una con su propia
cuenta de Claude Code y su propia máquina. Las cuentas no comparten entorno empresarial,
así que los agentes no tienen ningún canal común.

Hoy la comunicación entre agentes ocurre así: el agente de Víctor escribe un `.md` con
preguntas, Víctor se lo pasa a Pablo por Telegram, Pablo se lo da a su agente, y el
proceso se repite en reversa. **Los humanos son el transporte.**

El objetivo es eliminar ese acarreo: que los agentes se comuniquen directamente entre sí,
de forma asíncrona, sin que las personas tengan que intervenir en cada intercambio.

## 2. Objetivo y no-objetivos

### Objetivo

Un servicio de mensajería y conocimiento compartido entre sesiones de agentes de
codificación, aislado por proyecto, autenticado por persona, y con entrega confiable.

### No-objetivos (explícitos)

| No-objetivo | Razón |
|---|---|
| Orquestar el servicio con un LLM | El servicio es un enrutador determinista. La inteligencia vive en los extremos (los agentes). Un LLM en medio lo haría lento, caro, no determinista y difícil de depurar. |
| Comunicación entre proyectos distintos | El aislamiento por proyecto es la garantía central de confianza. Cruzarlo obliga a resolver permisos y fugas de contexto entre clientes distintos. Si algún día hace falta, será un puente explícito aprobado por ambas partes, nunca capacidad por defecto. |
| Usar Telegram como transporte | Era el plan B cuando no había dónde levantar el servicio. Con servicio propio, sobra. Telegram puede volver después, pero solo para notificar humanos. |
| Reemplazar Git | El código sigue viviendo en GitHub. Este servicio transporta *coordinación*, no artefactos de código. |
| Editar documentos de conocimiento en línea (WYSIWYG) | Los agentes mandan aportaciones; el servicio las aplica y versiona. |

## 3. Modelo de identidad

Tres niveles. Este es el corazón del diseño.

```
proyecto  →  el "cuarto". Frontera dura de aislamiento.
  persona →  el humano dueño de la cuenta. Se autentica con token.
    sesión → una instancia viva de agente, con un rol como etiqueta.
```

**Dirección pública de un agente:** `persona.rol` dentro de un proyecto.

Ejemplo real del escenario de Víctor:

| Proyecto | Persona | Rol | Dirección |
|---|---|---|---|
| `proyecto-pablo` | victor | `backend` | `victor.backend` |
| `proyecto-pablo` | victor | `db` | `victor.db` |
| `proyecto-pablo` | pablo | `general` | `pablo.general` |
| `proyecto-luis` | victor | `backend` | `victor.backend` |
| `proyecto-luis` | luis | `db` | `luis.db` |

Notas de diseño:

- **El rol es una etiqueta de dirección, no un contrato de responsabilidades.** Pablo
  trabaja con un solo agente que hace de todo: registra el rol `general` y funciona igual.
  Si mañana separa tareas, solo cambia la etiqueta al registrar la sesión.
- Se usa el rol como dirección pública, y no un identificador aleatorio, porque permite
  escribirle "al de base de datos" sin saber qué sesión concreta está viva.
- El `session_key` aleatorio existe por debajo, para reconexiones y para desambiguar si
  alguien registra dos sesiones con el mismo rol.
- Si hay dos sesiones vivas con el mismo `persona.rol`, el mensaje se ofrece a ambas y
  aplica el reclamo atómico (§5.3).

### 3.1 Los proyectos los crea un administrador

**Ningún agente puede crear un proyecto ni agregarse a uno.** La API de agentes no expone
esas operaciones; se hacen desde el panel (§9).

El motivo es el aislamiento. Si un agente pudiera crear proyectos, uno confundido levanta
un cuarto nuevo, se registra ahí, y queda hablando solo mientras cree que está coordinado.
Ese fallo es silencioso, que es la peor clase. Además, quién participa en un proyecto es
una decisión de personas, no de agentes.

El token no crea nada: solo permite registrarse en proyectos donde su persona **ya** es
miembro. Si no lo es, `403`, y el `detail` debe decir explícitamente *"pídele a tu
administrador que te agregue"* para que el agente no improvise probando slugs.

### 3.2 Bootstrap: credenciales y elección de proyecto

Secuencia obligatoria al arrancar una sesión de agente. Es una **compuerta dura**: sin
proyecto y rol confirmados por la persona, no hay `POST /sessions`.

1. **El token viene del entorno, siempre.** `MESH_TOKEN` como variable de entorno del
   sistema. Nunca se pregunta en el chat (quedaría en el historial y en las
   transcripciones), nunca se guarda en un archivo dentro del repo, ni en `.env`, ni en la
   carpeta de la skill. Un solo lugar donde buscarlo. Si falta, el cliente imprime la
   instrucción según el sistema operativo (`export` en `~/.zshrc` o `~/.bashrc`;
   `SetEnvironmentVariable` o `setx` en Windows) y se detiene.

   Esto también resuelve el caso de una misma persona con la misma cuenta trabajando desde
   una terminal en un servidor, VS Code en otro, y una laptop Windows: cada máquina
   configura su token una vez, y el estado no viaja con la skill.

2. **El token se comparte entre los agentes de una persona; la sesión no.** Dos agentes de
   Víctor usan el mismo `MESH_TOKEN` y obtienen dos `session_key` distintos con roles
   distintos. Eso es correcto y deseado.

3. **Con token válido, se listan los proyectos de la persona** (`GET /projects`, §8).
   Lista vacía significa que no ha sido agregada a ninguno: el agente se detiene y lo
   reporta.

4. **El agente propone, la persona confirma.** Puede sugerir un proyecto por coincidencia
   con el nombre del directorio de trabajo y un rol por lo que observó del repo, pero es
   una sugerencia. Se pregunta incluso si solo hay un proyecto en la lista.

5. **Solo con la confirmación explícita se llama a `register`.**

El estado de sesión resultante sí se guarda localmente, en `.agent-mesh/session.json` del
directorio de trabajo. Ese archivo contiene `session_key`, dirección y proyecto — **nunca
el token**. Consecuencia operativa: dos agentes de la misma persona deben correr en
**directorios distintos**, o se pisan el archivo de sesión.

## 4. Stack e infraestructura

| Componente | Decisión | Nota |
|---|---|---|
| Lenguaje / framework | Python 3.12 + FastAPI | |
| Persistencia | **SQLite** vía SQLAlchemy | Volumen diminuto (unos mensajes por hora). Transacciones reales, que es todo lo que se necesita para el reclamo atómico. |
| Migración futura | Postgres | La capa de datos se escribe con SQLAlchemy ORM y **sin SQL específico de SQLite**, para que migrar sea cambiar `DATABASE_URL`. Usar Alembic desde el commit inicial. |
| Migraciones | Alembic | Desde el día uno, aunque el esquema esté vacío. |
| Transporte | HTTP + **long polling** (§5.4) | |
| Empaquetado | Docker Compose (compatible con Podman) | Evitar features exclusivas de Docker: sin `depends_on: condition`, sin bind-mounts con permisos raros. |
| Exposición | Un solo puerto → túnel de Cloudflare | API y panel en el mismo proceso FastAPI. |
| Hashing de contraseñas | Argon2id (`argon2-cffi`) | Nunca texto plano, nunca MD5/SHA sueltos. |

### 4.1 Variables de entorno

> **Atención — dos dominios distintos e independientes.** No los mezcles, no derives uno
> del otro, no compartas variable.

| Variable | Ejemplo | Uso |
|---|---|---|
| `ADMIN_EMAIL_DOMAIN` | `empresa-interna.com` | Dominio de correo **obligatorio** para dar de alta usuarios del panel de administración. Cualquier alta con otro dominio se rechaza. |
| `PUBLIC_SERVICE_DOMAIN` | `mesh.otrodominio.dev` | Dominio público por el que se expone el servicio vía Cloudflare. **Sin relación alguna con el anterior.** |
| `DATABASE_URL` | `sqlite:////data/mesh.db` | |
| `BOOTSTRAP_ADMIN_EMAIL` | `victor@empresa-interna.com` | Se crea al primer arranque. |
| `LONGPOLL_MAX_SECONDS` | `30` | |
| `SESSION_STALE_AFTER_SECONDS` | `300` | Sin heartbeat → sesión marcada `stale`. |
| `LOG_LEVEL` | `INFO` | |

## 5. Mensajería

### 5.1 Anatomía de un mensaje

Cada mensaje lleva cabecera de ruteo, para que un agente pueda descartar de inmediato lo
que no le toca:

```json
{
  "project": "proyecto-pablo",
  "thread_id": "thr_8f2a…",
  "from": "victor.db",
  "to": "pablo.general",
  "kind": "question",
  "subject": "Contrato de /v1/orders: ¿paginación por cursor o por offset?",
  "body": "…markdown largo…",
  "in_reply_to": "msg_1c9e…"
}
```

- `to` puede ser `null` → el mensaje nace directamente en la bandeja de no reclamados.
- `kind` ∈ `question | answer | notice | proposal | agreement`.
- `body` es Markdown. Se espera que sea **largo**: es el sustituto de los `.md` que hoy
  se pasan por Telegram.

### 5.2 Estados y ciclo de vida

```
pending ──delivered──▶ delivered ──ack──▶ in_progress ──answer──▶ answered
   │                       │
   │                       └── (sesión destino muere / stale) ──▶ unclaimed
   └── (rol destino no existe) ──▶ unclaimed
```

**Un mensaje dirigido a un rol que todavía no existe NO se rechaza.** Queda en espera.
Así el agente de Víctor puede escribirle a `pablo.db` aunque Pablo aún no haya levantado
esa sesión.

### 5.3 Bandeja de no reclamados

Los mensajes sin destinatario vivo quedan visibles para **todas** las sesiones del
proyecto. Cada agente la revisa periódicamente y puede:

1. **Reclamar** (`claim`) → el servicio lo marca como tomado por esa sesión; nadie más lo
   ve. **La operación debe ser atómica**: si dos agentes reclaman a la vez, exactamente
   uno gana (transacción con `UPDATE … WHERE claimed_by IS NULL`, verificando `rowcount`).
2. **Descartar** (`dismiss`) → el servicio recuerda que *esa sesión* ya lo descartó y no
   se lo vuelve a mostrar. Otras sesiones lo siguen viendo.
3. Ignorar → se lo volverá a mostrar.

Cuando alguien reclama un mensaje que iba dirigido a otro rol, **el servicio notifica al
remitente** con un mensaje de `kind: notice`. Así el emisor sabe quién acabó atendiéndolo.

### 5.4 Long polling y los dos relojes

Hay que separar dos tiempos que se confunden fácil:

| Reloj | Duración | Significado |
|---|---|---|
| Timeout de la conexión HTTP | ~30 s (`LONGPOLL_MAX_SECONDS`) | "No hay nada nuevo ahora, vuelve a preguntar". **Nada que ver con el otro agente.** |
| Tiempo de la conversación | minutos u horas | Lo que tarda el otro agente en leer, razonar, trabajar y contestar. |

`GET /inbox` retiene la conexión hasta `LONGPOLL_MAX_SECONDS` y responde en cuanto haya
algo. Esto da casi tiempo real sin cambiar arquitectura. Si más adelante hace falta,
se añade SSE o WebSocket **sin tocar el modelo de datos**.

**El agente nunca se bloquea esperando respuesta.** Manda la pregunta, sigue con otra
cosa, y revisa después. El estado `in_progress` existe para que el remitente vea "Pablo lo
está trabajando" en lugar de quedarse en el aire o reenviar.

### 5.5 Entrega exactamente-una-vez

Cada entrega se registra en `message_deliveries`. El agente confirma con `ack`. Si una
sesión muere sin hacer `ack` dentro de `SESSION_STALE_AFTER_SECONDS`, el mensaje vuelve a
`pending` o cae a `unclaimed`. Esto elimina la pelea entre múltiples sesiones por el mismo
mensaje.

### 5.6 Agentes de la misma persona

Se habilita desde el principio: `victor.backend` puede escribirle a `victor.db` dentro del
mismo proyecto. Mismo mecanismo, sin excepciones.

## 6. Conocimiento persistido

### 6.1 Alcance de la primera etapa

**Se implementa ligero, pero se diseña para crecer.** Al inicio: unos pocos documentos de
convenciones por proyecto y los acuerdos cerrados entre agentes. Lo genuinamente valioso
son los acuerdos: cuando dos agentes cierran un contrato de API, queda escrito y ambos lo
consultan después, en vez de renegociarlo.

La razón de no darle alcance completo ya (repositorio único de conocimiento del proyecto):
todavía no sabemos cómo se comportan los agentes escribiendo documentación compartida.
Eso hay que verlo en vivo antes de construir estructura encima.

Pero desde el día uno cada documento se guarda con **identificador, versión y autor**, así
que convertirlo después en el repositorio de conocimiento del proyecto no requiere migrar
nada.

### 6.2 Estructura de directorios (convención, fija desde el inicio)

Los documentos se guardan en base de datos, pero su `path` sigue esta convención jerárquica:

```
<project-slug>/
├── 00-conventions/          # Reglas del cuarto. Casi estático.
│   ├── messaging.md         # Cómo se dirigen y formatean los mensajes
│   ├── roles.md             # Qué roles existen y quién es quién
│   └── doc-style.md         # Cómo se escribe en esta base de conocimiento
├── 10-architecture/         # Diseño del sistema
│   ├── overview.md
│   └── <componente>.md
├── 20-contracts/            # ⭐ Acuerdos cerrados. Lo más valioso.
│   ├── api-<recurso>.md     # Contratos cliente/servidor
│   └── schema-<tabla>.md    # Contratos de datos
├── 30-decisions/            # ADRs. Uno por decisión, inmutables.
│   └── NNNN-<slug>.md
└── 90-scratch/              # Notas en vuelo. Purgables sin duelo.
```

Los prefijos numéricos ordenan y señalan estabilidad: número bajo = más estable.

### 6.3 Escritura concurrente

**Los agentes no editan el archivo.** Mandan una *aportación*:

```json
{
  "document_path": "20-contracts/api-orders.md",
  "base_version": 7,
  "intent": "amend",
  "anchor": "## Paginación",
  "content": "…markdown…",
  "rationale": "Acordado con pablo.general en thr_8f2a"
}
```

- `intent` ∈ `create | append | amend | deprecate`
- `deprecate` **no borra**: marca el bloque como obsoleto, lo mueve al final del documento
  bajo `## Obsoleto`, y anota quién y por qué.
- El servicio aplica la aportación y guarda la **versión completa resultante**. Nunca
  sobrescribe a ciegas.

**Control de concurrencia optimista:** el agente declara sobre qué `base_version` trabajó.
Si el documento ya cambió, el servicio responde `409 Conflict` con la versión actual y el
diff, y el agente debe releer y reintentar.

Cada versión conserva autor (`persona.rol`), timestamp, `intent` y `rationale`. El
historial completo es consultable.

## 7. Esquema de datos

```
admin_users        id, email, password_hash, role, is_active,
                   created_at, last_login_at, must_change_password

people             id, email, display_name, is_active, created_at
access_tokens      id, person_id, token_hash, label, created_at,
                   last_used_at, revoked_at

projects           id, slug, name, description, is_active, created_at
project_members    project_id, person_id, joined_at

sessions           id, project_id, person_id, role_label, session_key,
                   status(active|stale|closed), registered_at,
                   last_seen_at, agent_metadata(json)

threads            id, project_id, subject,
                   status(open|in_progress|resolved),
                   created_at, updated_at

messages           id, project_id, thread_id, in_reply_to,
                   sender_session_id, sender_address,
                   recipient_address(nullable), kind, subject, body,
                   status, claimed_by_session_id, claimed_at, created_at

message_deliveries message_id, session_id, delivered_at, acked_at
message_dismissals message_id, session_id, dismissed_at

documents          id, project_id, path, title, current_version,
                   status(active|archived), created_at, updated_at
document_versions  id, document_id, version, content, intent,
                   rationale, author_address, author_session_id,
                   created_at
```

Índices mínimos: `messages(project_id, recipient_address, status)`,
`messages(project_id, status)` para la bandeja de no reclamados,
`sessions(project_id, person_id, role_label)`, `documents(project_id, path)` único.

## 8. API para agentes

Prefijo `/api/v1`. Autenticación: `Authorization: Bearer <token-de-persona>`.

### Proyectos
| Método | Ruta | Nota |
|---|---|---|
| `GET` | `/projects` | **Solo lectura.** Proyectos donde la persona del token ya es miembro. Base del bootstrap (§3.2). |

No hay `POST /projects` ni endpoint de auto-membresía en esta API. Es deliberado (§3.1).
Respuesta: `{person, projects: [{slug, name, members}]}`. Lista vacía es válida y significa
"todavía no te agregan a ninguno".

### Sesiones
| Método | Ruta | Nota |
|---|---|---|
| `POST` | `/sessions` | Registra sesión. Body: `{project, role}`. Devuelve `session_key`. `403` si la persona no es miembro, con `detail` accionable. |
| `POST` | `/sessions/{key}/heartbeat` | Mantiene viva la sesión. |
| `DELETE` | `/sessions/{key}` | Cierre limpio. |
| `GET` | `/projects/{slug}/roster` | Quién está vivo ahora mismo. |

### Mensajes
| Método | Ruta | Nota |
|---|---|---|
| `POST` | `/messages` | Enviar. |
| `GET` | `/inbox?wait=30` | **Long poll.** Mensajes dirigidos a esta sesión. |
| `POST` | `/messages/{id}/ack` | Confirma recepción. |
| `POST` | `/messages/{id}/progress` | Marca `in_progress`. |
| `GET` | `/unclaimed` | Bandeja de no reclamados, filtrando los ya descartados por esta sesión. |
| `POST` | `/messages/{id}/claim` | **Atómico.** `409` si otro ganó. |
| `POST` | `/messages/{id}/dismiss` | Descarte por sesión. |
| `GET` | `/threads/{id}` | Hilo completo. |

### Conocimiento
| Método | Ruta | Nota |
|---|---|---|
| `GET` | `/projects/{slug}/docs` | Índice (path, título, versión). |
| `GET` | `/docs?path=…` | Documento con `current_version`. |
| `POST` | `/docs/contributions` | Aportación (§6.3). `409` en conflicto de versión. |
| `GET` | `/docs/{id}/versions` | Historial. |

## 9. Panel de administración

Ruta `/admin`. Server-rendered, sin framework de frontend. Sesión por cookie.

- Login con **correo + contraseña**. El correo debe pertenecer a `ADMIN_EMAIL_DOMAIN`.
- Al primer arranque se crea el admin de `BOOTSTRAP_ADMIN_EMAIL` con contraseña aleatoria
  **impresa en los logs del contenedor** y `must_change_password = true`.
- Funciones mínimas de la v1: crear proyecto, dar de alta persona, asignar persona a
  proyecto, emitir y revocar tokens, ver sesiones vivas, navegar mensajes y documentos.
- CRUD de administradores: **la tabla y el campo `role` existen desde el día uno**, la
  interfaz de gestión se implementa después.

**Seguridad:** el panel se protege con usuario y contraseña propios, y esto *reemplaza* a
Cloudflare Access, no lo complementa. Es aceptable siempre que **el túnel de Cloudflare sea
el único camino de entrada** al contenedor (no publicar el puerto al host ni a la LAN).

## 10. Orden de implementación sugerido

1. Esqueleto FastAPI + SQLAlchemy + Alembic + Compose + healthcheck.
2. Esquema completo (todas las tablas de §7, aunque no todas se usen aún).
3. Bootstrap del admin, login, y CRUD mínimo de proyectos/personas/tokens.
4. `GET /projects`, registro de sesiones, heartbeat, roster.
5. Envío + inbox con long polling + ack.
6. Bandeja de no reclamados: claim atómico, dismiss, notice al remitente.
7. Documentos: lectura, aportaciones, versionado, conflicto optimista.
8. Panel: vistas de solo lectura sobre mensajes y documentos.
9. *(Después, documento aparte)* La skill del lado del agente.

## 11. Pruebas críticas

- **Claim concurrente:** N sesiones reclaman el mismo mensaje en paralelo → exactamente una
  gana. Test con hilos reales, no secuencial.
- **Conflicto de documento:** dos aportaciones con la misma `base_version` → la segunda
  recibe `409`.
- **Aislamiento:** un token del proyecto A no puede leer nada del proyecto B. Ni mensajes,
  ni roster, ni documentos.
- **Bootstrap:** `GET /projects` con un token nuevo devuelve solo los proyectos de esa
  persona; `POST /sessions` a un proyecto donde no es miembro devuelve `403` con `detail`
  accionable, y a un slug inexistente devuelve `404`. Ninguna ruta permite crear proyectos.
- **Sesión muerta:** mensaje entregado sin `ack` a sesión que se vuelve `stale` → reaparece.
- **Dismiss por sesión:** A descarta, B lo sigue viendo.
- **Dominio de admin:** alta con correo de otro dominio → rechazada.
