# Prueba de aceptación del plugin v0.2

Antes y después de cualquier cambio al plugin, como el 27 de agosto. Requiere:
servidor levantado, **dos tokens** de personas distintas, y **dos directorios
distintos** (p. ej. `/tmp/agente-a` y `/tmp/agente-b`) — dos `session.json` en
el mismo cwd se pisan.

- [ ] 1. `/agent-mesh:setup` con entorno limpio → imprime la instrucción de
      instalación para el SO y se detiene, sin pedir el token por chat. Con
      entorno completo → una línea ("ya está configurado") y fin.
- [ ] 2. `/agent-mesh:register` en frío → propone proyecto y rol citando
      directorio y roster, y pregunta. Repetido → "ya estás registrado"
      (idempotente). Tras matar la sesión (borrarla del panel o dejarla
      caducar) → registra de nuevo **sin volver a preguntar** proyecto/rol ya
      confirmados en la misma sesión de trabajo.
- [ ] 3. `/agent-mesh:monitor` en A + `mesh.py send` desde B → el archivo
      aparece en `.agent-mesh/inbox/` de A **antes** del ack (verificar orden
      en `monitor.log`: la línea del mensaje precede a cualquier fallo de ack,
      y el JSON persistido trae `thread_id`).
- [ ] 4. Matar la sesión de B (`mesh.py close` o panel) y esperar
      `--idle-exit-minutes` → el monitor de A sale con **código 2** y última
      línea `ABANDONO:` con dirección y asunto pendiente.
- [ ] 5. `/agent-mesh:stop` con un hilo terminado → contribución en
      `20-contracts/` citando el `thread_id` en el rationale, hilo `resolved`
      (`mesh.py threads --status resolved` lo muestra), y reporte final con
      mensajes atendidos / acuerdos / hilos abiertos.
- [ ] 6. En todo el escenario, **no redirigir salidas a `/dev/null`**: un
      `send` desde el directorio equivocado falla en silencio y parece bug del
      servidor.

Solo cuando todo pasa: copiar `plugin/` sobre `agent-mesh/` en
`vimsanchez/vimasamo-skills` (la versión de `plugin.json` ya viaja en la
copia). La sincronización sigue siendo manual; sigue siendo el punto frágil
conocido.
