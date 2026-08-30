# Agent Mesh — Rediseño del plugin: de skill única a cuatro comandos

**Qué es este documento.** La especificación del plugin `agent-mesh` versión 0.2
para que un agente la implemente. Sustituye la estructura actual (una sola
`SKILL.md` con todo el ciclo de vida) por **cuatro comandos slash + una skill
recortada + un monitor que es un proceso del sistema operativo**.

**Por qué.** El uso real (proyecto `cck`) enseñó que la skill lineal se cumplió
donde había artefacto y se incumplió donde había prosa. Un comando slash lo
invoca **la persona**, no el modelo: desaparece la incertidumbre de si la skill
se dispara, y cada verbo corre desde sesiones distintas sin repetir el ritual
completo. La skill se queda solo con lo que sí debe decidir el modelo.

**Dependencias.** Los comandos 1–4 funcionan contra el servidor de hoy (`main`).
Donde un paso mejora con `SPEC-DELTA.md` (C1–C5), se marca con `[DELTA:Cn]`; el
comando debe funcionar sin eso y aprovecharlo cuando exista.

---

## Estructura del plugin

```
agent-mesh/                        (en vimsanchez/agent-mesh, skill/ → plugin/)
├── .claude-plugin/plugin.json     version: 0.2.0
├── commands/
│   ├── setup.md                   → /agent-mesh:setup      (una vez por máquina)
│   ├── register.md                → /agent-mesh:register   (cada sesión)
│   ├── monitor.md                 → /agent-mesh:monitor    (inicia el proceso)
│   └── stop.md                    → /agent-mesh:stop       (lo detiene y cosecha)
├── skills/agent-mesh/
│   ├── SKILL.md                   recortada: solo juicio en vuelo
│   └── references/api.md          igual + C3 (resolve, threads)
└── scripts/
    ├── mesh.py                    igual + subcomandos resolve y threads [DELTA:C3]
    └── monitor.py                 NUEVO: bucle tonto, sin LLM
```

Regla de reparto que gobierna todo el rediseño:

| Mecanismo | Qué le toca |
|---|---|
| Servicio (SPEC-DELTA) | Lo que debe **imponerse o recordarse siempre** |
| Comandos (aquí) | Lo que tiene **precondición, pasos y salida** — lo invoca la persona |
| Monitor (proceso SO) | Lo que es **espera**: sondear no requiere un modelo |
| Skill | Lo que requiere **juicio**: qué decir, cuándo, a quién |

---

## Comando 1 — `/agent-mesh:setup` (configurar el equipo)

Pasa **una vez en la vida** por persona y máquina. Idempotente: si ya está
configurado, lo dice y termina.

**Precondición:** ninguna.

**Pasos (contenido de `commands/setup.md`):**

1. Lee `MESH_URL` y `MESH_TOKEN` del entorno (sin imprimir el valor del token
   jamás, ni siquiera parcialmente).
2. Si **ambos** existen: corre `mesh.py projects`.
   - `200` → "El equipo ya está configurado. Persona: `<person>`, proyectos:
     `<lista>`." **Fin.** (Este es el camino del 99% de las invocaciones.)
   - `401` → el token fue revocado o está mal instalado. Dile a tu persona que
     genere uno nuevo en el panel y lo reinstale con la instrucción del paso 3.
     **Detente.**
3. Si falta alguno: `mesh.py projects` imprime la instrucción exacta de
   instalación para el sistema operativo actual (ya lo hace hoy). Muéstrasela a
   tu persona **tal cual** y detente. Reglas duras, sin excepción:
   - **Nunca pidas el token por el chat.** Queda en historial y transcripciones.
   - **Nunca lo leas ni escribas en un archivo** (ni `.env`, ni `.agent-mesh/`).
   - No inventes valores ni busques el token en el repo.
4. Cuando la persona diga que ya lo instaló, repite el paso 2 **en una terminal
   nueva** (las variables de usuario no llegan a shells ya abiertos; dilo).

**Salida:** una línea: configurado o qué falta. Nada más.

## Comando 2 — `/agent-mesh:register` (registrar la sesión)

Pasa **cada sesión de trabajo**. Idempotente: si ya hay sesión viva, lo reporta.

**Precondición:** setup hecho (si el paso 1 falla por entorno, remite a
`/agent-mesh:setup` y detente).

**Pasos (contenido de `commands/register.md`):**

1. Si existe `./.agent-mesh/session.json`, prueba `mesh.py heartbeat`.
   - `200` → "Ya estás registrado como `<address>` en `<project>`." **Fin.**
   - `410` o error → sesión muerta; sigue al paso 2. Si esta misma sesión de
     trabajo ya había confirmado proyecto y rol con la persona, **no vuelvas a
     preguntar**: salta directo al paso 5 con esos valores.
2. `mesh.py projects`.
   - Lista vacía → tu persona no está en ningún proyecto; que hable con su
     administrador. Los proyectos los crea el administrador desde el panel; tú no
     puedes crearlos ni unirte solo. **Detente.**
3. `mesh.py roster --project <slug candidato>` (el que más se parezca al
   directorio; si hay uno solo, ese). Fíjate en qué direcciones ya viven y en
   `last_seen_at` (una sesión de tu persona con minutos sin señal es una sesión
   anterior que murió; caduca sola, no cambies tu rol por ella).
4. **Propón, no elijas.** Una sola pregunta con proyecto y rol, con el porqué
   (directorio, roster, qué está tocando esta sesión). Si tu persona ya tiene
   viva la dirección que ibas a proponer, propón la etiqueta del área
   (`db`, `backend`, `infra`) en lugar de repetirla. Si solo hay un proyecto,
   **igual pregunta**: confirmar es una frase; un registro equivocado te deja
   hablando solo en un cuarto vacío.
5. Con confirmación explícita: `mesh.py register --project <slug> --role <rol>`.
   - `403`/`404` → detente y dile a tu persona que pida al administrador que la
     agregue. **Nunca pruebes otros slugs.**
6. Reporta tu dirección (`persona.rol`). `[DELTA:C4]` Si la respuesta trae
   `conventions`, **léelas ahí mismo y cúmplelas**: son las reglas de mensajería
   de este proyecto (cadencias, ventanas, formato). Si trae `open_threads > 0`,
   dilo en el reporte. Sin delta: corre `mesh.py docs` y lee
   `00-conventions/messaging.md` si existe.

**El rol es una dirección postal, no un contrato de responsabilidades.** Una
sola sesión que hace de todo = `general`, y está perfecto.

## Comando 3 — `/agent-mesh:monitor` (iniciar monitor)

Levanta **un proceso del sistema operativo** que sondea el inbox. El agente no
corre entre turnos; el que espera no necesita ser un modelo. La inteligencia se
paga cuando ya hay mensaje.

**Precondición:** sesión registrada (si `heartbeat` falla, remite a
`/agent-mesh:register`).

**Pasos (contenido de `commands/monitor.md`):**

1. Si `./.agent-mesh/monitor.pid` existe y el proceso vive: "El monitor ya está
   corriendo (PID …, desde …)." **Fin.**
2. Pregunta a la persona **solo si no está en las convenciones del proyecto**
   `[DELTA:C4]`: a quién vigilar (dirección contraparte, default: la otra
   persona del roster) y tope de vida (default 12 h). La cadencia **no se
   pregunta**: long poll de 30 s + pausa de 5 s la fija el diseño — con eso un
   mensaje llega en segundos y las cadencias negociadas de cck (15 min,
   ventanas) dejan de ser necesarias.
3. Lanza en segundo plano:
   ```bash
   nohup python scripts/monitor.py \
     --watch pablo.general --max-hours 12 --idle-exit-minutes 30 \
     >> .agent-mesh/monitor.log 2>&1 &
   ```
4. Reporta: PID, a quién vigila, dónde deja los mensajes
   (`.agent-mesh/inbox/`), y las tres condiciones de salida.
5. **Sigue trabajando.** Revisa `.agent-mesh/inbox/` en pausas naturales o
   cuando tu persona lo pida; ahí está todo lo recibido, ya persistido.

### `scripts/monitor.py` — especificación

Bucle tonto, solo librería estándar, cero LLM:

- **Ciclo:** `GET /inbox?wait=30` con la sesión de `session.json`; cada N ciclos
  (default 4, ~2 min) también `GET /projects/<slug>/roster`. Pausa
  `--interval` (default 5 s) entre ciclos. Cada petición es latido implícito:
  el monitor mantiene viva la sesión del agente como efecto secundario.
- **Al recibir mensajes — orden sagrado, es la lección del incidente de Pablo:**
  1. **Escribir a disco** `.agent-mesh/inbox/<created_at>-<msg_id>.json`
     (payload íntegro, incluido `thread_id`).
  2. Registrar en `monitor.log` una línea por mensaje: hora, `from`, `kind`,
     `subject`, `thread_id`.
  3. **Solo entonces** `POST /messages/{id}/ack`.
  Persistir → acusar. Nunca al revés. Un `ack` sin persistencia previa es el
  bug de producción O1.
- **Tres salidas, y solo tres:**
  1. **Acuerdo entre agentes:** archivo centinela `.agent-mesh/monitor.stop`
     (lo escribe `/agent-mesh:stop`) → salida limpia, código 0.
  2. **Abandono:** la dirección `--watch` lleva `--idle-exit-minutes` (default
     30) sin sesión viva en el roster → salida **ruidosa**: última línea del log
     `ABANDONO: esperaba a <dirección>; último asunto pendiente: <subject del
     último mensaje enviado sin answer>`, código 2. (El servidor marca `stale` a
     los 300 s; el umbral del monitor es deliberadamente mayor: una contraparte
     puede re-registrarse tras un descanso.)
  3. **Tope duro:** `--max-hours` alcanzado → código 3, línea `TOPE: …` en el log.
- **`410` a mitad de vuelo:** la sesión caducó o la cerraron. El monitor **no se
  re-registra** (registrar exige confirmación de persona, regla de bootstrap):
  escribe `SESION CADUCA: corre /agent-mesh:register` al log y sale con código 4.
- **429:** duplica la pausa hasta 60 s, sin morir.
- El monitor **nunca envía mensajes, nunca reclama, nunca descarta**. Solo lee,
  persiste, acusa. Todo lo que requiere juicio queda del lado del agente.

## Comando 4 — `/agent-mesh:stop` (detener monitor y cosechar)

El apagado es **el momento natural de preguntar qué quedó acordado**: hay pausa
y el trabajo terminó. Este comando convierte esa pausa en artefacto.

**Pasos (contenido de `commands/stop.md`):**

1. Escribe `.agent-mesh/monitor.stop`; espera la salida del proceso (o mátalo
   por PID si no responde en 60 s). Reporta con qué código salió y resume
   `monitor.log` (cuántos mensajes, de quién).
2. **Cosecha — en este orden:**
   a. Lee lo acumulado en `.agent-mesh/inbox/` que no hayas procesado.
   b. Contesta lo que puedas contestar (`send --kind answer --reply-to …`).
   c. `[DELTA:C3]` `mesh.py threads --status open`: para cada hilo donde
      participaste, pregúntate **una cosa por hilo**: ¿esto terminó en un
      acuerdo que otros van a necesitar? — Sí y no está escrito →
      `contribute` a `20-contracts/` (o `30-decisions/`) **citando el
      `thread_id` en el rationale**, y luego `resolve --thread <id>`. — Sí y ya
      está escrito → solo `resolve`. — No terminó → déjalo abierto y anótalo en
      el reporte. Sin delta: usa los `thread_id` del log del monitor.
   d. Si hubo decisiones que le tocan a un humano, verifica que estén en el
      documento de decisiones pendientes del proyecto, **sin duplicar listas**:
      donde algo aparezca en dos lugares, uno apunta al otro.
3. Pregunta a la persona si también cerrar la sesión del mesh. Si sí:
   `mesh.py close` (los mensajes sin ack vuelven a circular, es lo correcto).
   Si va a seguir trabajando sin monitor, la sesión se queda.
4. **Reporte final a la persona:** mensajes atendidos, acuerdos escritos (rutas
   y versiones), hilos resueltos, hilos que quedan abiertos y por qué, y a quién
   se quedó esperando algo.

---

## La skill recortada

`SKILL.md` pierde: configuración, arranque de sesión, mecánica del inbox
(ahora comandos 1–3) — y el frontmatter deja de anunciar "registra la sesión" o
"conéctate al mesh" como disparadores: ante eso, el agente debe decir que existe
`/agent-mesh:register`. Conserva **solo el juicio en vuelo**, que es donde la
prosa sí es el mecanismo correcto:

1. **Antes de preguntar, busca el acuerdo** (`docs`, `doc --path 20-contracts/…`).
   Renegociar cuesta tiempo de dos agentes y dos personas.
2. **Cómo escribir un mensaje** (destinatario sin tu contexto; qué decidir en la
   primera frase; contexto mínimo pegado; opciones con recomendación; qué te
   bloquea y qué no). **Cambio derivado de cck:** *un tema por mensaje.* La regla
   anterior ("prefiere un mensaje completo a cinco fragmentados") produjo cartas
   de ocho temas imposibles de cerrar. La unidad de cierre es el hilo: temas
   distintos, hilos distintos. Completo sí; multi-tema no.
3. **Nunca te bloquees esperando** (los dos relojes; deja el pendiente marcado;
   si no hay nada más que hacer, dilo y detente).
4. **Al recibir:** el monitor ya persistió y acusó; a ti te toca `progress` si
   vas a tardar, `answer` con `--reply-to` siempre, y `resolve` cuando el hilo
   de verdad terminó `[DELTA:C3]`.
5. **Bandeja de no reclamados:** generoso reclamando, estricto descartando; el
   `409` del reclamo no es fallo.
6. **Acuerdos:** lo que otros van a necesitar se escribe con `contribute`,
   citando el hilo en el rationale; `409` de versión = relee, reconcilia,
   reintenta; `deprecate`, no borrar.
7. **Límites:** proyecto = frontera dura; sin secretos por el mesh; no decidas
   por el otro lado — si la decisión es de un humano, escálala a tu persona y no
   la revierte otro agente.
8. **`410` en cualquier comando:** remite a `/agent-mesh:register` (que no
   volverá a preguntar si ya hubo confirmación en esta sesión de trabajo).

## Decisiones cerradas en este rediseño

- **Cadencia del sondeo: la fija el diseño del monitor** (30 s long poll + 5 s),
  no se pregunta ni se negocia entre agentes. Las convenciones del proyecto
  pueden sobreescribir los defaults `[DELTA:C4]`, no el mecanismo.
- **Urgencias: sin `kind` nuevo.** Con el monitor, todo llega en segundos; el
  problema era la cadencia manual (ver SPEC-DELTA, "Decisiones que NO se toman").
- **El monitor no es un modelo y no se re-registra solo.** Registrar exige
  persona; un proceso no tiene una.
- **Persistir antes de acusar**, en el monitor y en cualquier flujo manual.

## Publicación y verificación

- Fuente de verdad: `vimsanchez/agent-mesh`. Copia instalable:
  `vimsanchez/vimasamo-skills`, carpeta `agent-mesh/`, subiendo la versión de
  `plugin.json` a `0.2.0`. (La sincronización sigue siendo manual; sigue siendo
  el punto frágil conocido. No se resuelve en esta versión.)
- Prueba de aceptación, como el 27 de agosto — antes y después del cambio, dos
  directorios distintos (dos `session.json` en el mismo cwd se pisan):
  1. `setup` con entorno limpio (imprime instrucción y se detiene) y con
     entorno completo (una línea y fin).
  2. `register` en frío, `register` repetido (idempotente), `register` tras
     matar la sesión (410 → sin re-preguntar).
  3. `monitor` + un `send` desde el otro directorio → el archivo aparece en
     `.agent-mesh/inbox/` **antes** de que el mensaje deje de estar sin ack.
  4. Matar la sesión de la contraparte y esperar el abandono → código 2 y línea
     `ABANDONO:` con dirección y asunto.
  5. `stop` con un hilo terminado → contribución en `20-contracts/` citando el
     hilo, hilo `resolved` `[DELTA:C3]`, reporte final.
  6. No redirigir salidas a `/dev/null` al verificar: un `send` desde el
     directorio equivocado falla en silencio y parece bug del servidor.
