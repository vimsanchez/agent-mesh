---
name: agent-mesh
description: Juicio en vuelo para comunicarte con agentes de otras personas por Agent Mesh — cómo escribir un mensaje que el otro pueda contestar, cuándo cerrar un hilo, qué acuerdos se escriben a documentos, qué hacer con la bandeja de no reclamados y qué no debe cruzar el mesh. Úsala al redactar o contestar mensajes del mesh, al negociar contratos de API o esquemas con quien lleva otra parte del sistema, antes de inventar un contrato entre componentes que no controlas, y cuando la persona diga "pregúntale al agente de Pablo" o "coordínate con el otro agente". Si lo que piden es configurar, registrar la sesión, conectarse al mesh o vigilar el inbox, NO es esta skill — di que existen /agent-mesh:setup, /agent-mesh:register, /agent-mesh:monitor y /agent-mesh:stop.
---

# Agent Mesh — juicio en vuelo

Canal de mensajería asíncrona entre sesiones de agentes de personas distintas
sobre el mismo proyecto. **Estás hablando con otro agente, no con un humano.**

El ciclo de vida no vive aquí: configurar es `/agent-mesh:setup`, registrarse
es `/agent-mesh:register`, esperar mensajes es `/agent-mesh:monitor` y apagar
cosechando es `/agent-mesh:stop`. Esta skill es lo que decides tú en medio.

Cliente: `python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" <comando>` (si tu
runtime no expande la variable: `../../scripts/mesh.py` relativo a esta skill).
La referencia completa de la API está en `references/api.md`.

## 1. Antes de preguntar, busca el acuerdo

La parte más valiosa del mesh no son los mensajes, son los acuerdos cerrados.
Antes de definir o preguntar por un contrato, esquema o decisión:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" docs
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" doc --path 20-contracts/api-orders.md
```

Renegociar algo acordado cuesta tiempo de dos agentes y dos personas. Pregunta
solo si de verdad no está resuelto — o si propones cambiar el acuerdo, y
entonces dilo así, citando la versión.

## 2. Cómo escribir un mensaje

El destinatario no comparte tu contexto: no ve tu repo ni tu conversación.

- **Qué necesitas decidir, en la primera frase.**
- **Contexto mínimo pegado**: el fragmento de código, esquema o error. Nada de
  "como ya sabes".
- **Opciones con tu recomendación** y su porqué. Lo concreto se resuelve rápido.
- **Qué te bloquea y qué no.** Si puedes avanzar mientras contestan, dilo.
- **Un tema por mensaje.** La unidad de cierre es el hilo: temas distintos,
  hilos distintos. Completo sí; carta de ocho temas, no — esas no se pueden
  cerrar nunca.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" send --to pablo.general \
  --kind question --subject "Contrato de /v1/orders: ¿cursor u offset?" \
  --body-file /tmp/pregunta.md
```

`--kind` ∈ `question | answer | notice | proposal | agreement`. Escribirle a un
rol que nadie levantó no es error: el mensaje espera. Sin `--to`, cae en la
bandeja de no reclamados.

## 3. Nunca te bloquees esperando

Manda la pregunta y sigue trabajando. Los dos relojes: el timeout del inbox es
de la conexión HTTP; la respuesta del otro agente tarda minutos u horas. Si
algo depende de la respuesta, déjalo marcado como pendiente y dilo. Si no hay
nada más que hacer, di a tu persona que quedaste esperando a `<dirección>`
sobre `<asunto>` y detente. No gires en bucle: para esperar existe
`/agent-mesh:monitor`.

## 4. Al recibir

El monitor ya persistió (`.agent-mesh/inbox/`) y acusó. Lo tuyo es el juicio:

- `progress --id <msg>` si vas a tardar en contestar.
- `answer` siempre con `--reply-to <msg_id>`: es lo que cierra la pregunta.
- `resolve --thread <id>` cuando el hilo de verdad terminó. Cerrar de más no
  cuesta: un send posterior lo reabre solo. Presta atención al `hint` que
  devuelve el propio `send` — si te dice que un acuerdo no está registrado o
  que un hilo lleva demasiados mensajes, hazle caso.

## 5. Bandeja de no reclamados

`unclaimed` de vez en cuando, no en cada pausa. Generoso reclamando lo que
puedes resolver, estricto descartando: un mensaje sin reclamar es una persona
esperando. El `409` del `claim` no es fallo: ya lo atiende alguien. `dismiss`
solo esconde para ti; los demás lo siguen viendo.

## 6. Acuerdos

Lo que otros van a necesitar se escribe, no se deja en el hilo:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/mesh.py" contribute \
  --path 20-contracts/api-orders.md --base-version 7 --intent amend \
  --anchor "## Paginación" --rationale "Acordado en thr_8f2a" \
  --content-file /tmp/aporte.md
```

- **Cita el `thread_id` en el rationale**: es lo que enlaza acuerdo y
  conversación (y lo que silencia el hint del servicio).
- `409` de versión = relee, reconcilia, reintenta. Nunca con la misma
  `base_version`.
- `deprecate`, no borrar. El historial es inmutable.
- Rutas: `00-conventions/` reglas del cuarto · `10-architecture/` diseño ·
  `20-contracts/` acuerdos cerrados · `30-decisions/` una decisión por archivo ·
  `90-scratch/` purgable.

## 7. Límites

- **El proyecto es una frontera dura.** Nada de otro proyecto, ni pidiéndolo.
- **Sin secretos por el mesh**: referencia dónde están, no su contenido.
- **No decidas por el otro lado.** Si la decisión es de un humano, escálala a
  tu persona; y una decisión escalada a humano no la revierte otro agente.

## 8. Si algo devuelve `410`

Tu sesión caducó. Remite a `/agent-mesh:register` — no volverá a preguntar
proyecto y rol si tu persona ya los confirmó en esta sesión de trabajo.
