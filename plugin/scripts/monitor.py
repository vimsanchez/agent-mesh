#!/usr/bin/env python3
"""Monitor de inbox de Agent Mesh: bucle tonto, solo librería estándar, cero LLM.

El agente no corre entre turnos; el que espera no necesita ser un modelo. Este
proceso sondea el inbox, y al recibir sigue el orden sagrado (incidente O1):

    1. persistir a disco    .agent-mesh/inbox/<created_at>-<msg_id>.json
    2. una línea en el log  hora, from, kind, subject, thread_id
    3. solo entonces        POST /messages/{id}/ack

Nunca envía, nunca reclama, nunca descarta, nunca se re-registra: registrar
exige confirmación de persona, y un proceso no tiene una.

Salidas:
    0  centinela .agent-mesh/monitor.stop (lo escribe /agent-mesh:stop)
    2  ABANDONO: la dirección vigilada lleva --idle-exit-minutes sin sesión viva
    3  TOPE: --max-hours alcanzado
    4  SESION CADUCA: 410 del servidor; corre /agent-mesh:register

Uso:
    nohup python monitor.py --watch pablo.general --max-hours 12 \
        --idle-exit-minutes 30 >> .agent-mesh/monitor.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# `timezone.utc` y no `datetime.UTC`: este script corre con el Python del
# sistema de cada persona, y `UTC` a secas solo existe desde 3.11.
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.cwd() / ".agent-mesh"
SESSION_FILE = STATE_DIR / "session.json"
INBOX_DIR = STATE_DIR / "inbox"
STOP_FILE = STATE_DIR / "monitor.stop"
PID_FILE = STATE_DIR / "monitor.pid"

EXIT_STOP = 0
EXIT_ABANDON = 2
EXIT_MAXHOURS = 3
EXIT_GONE = 4


def log(linea: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {linea}", flush=True)


def _session() -> dict:
    return json.loads(SESSION_FILE.read_text())


def request(method: str, path: str, params: dict | None = None, timeout: int = 60) -> dict:
    """Petición autenticada. Toda petición con sesión es latido implícito."""
    url = os.environ["MESH_URL"].rstrip("/") + "/api/v1" + path
    if params:
        limpio = {k: v for k, v in params.items() if v is not None}
        if limpio:
            url += "?" + urllib.parse.urlencode(limpio)
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['MESH_TOKEN']}",
            "Accept": "application/json",
            "X-Mesh-Session": _session()["session_key"],
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def persist(msg: dict) -> Path:
    """Escribe el payload íntegro a disco. SIEMPRE antes del ack.

    Escritura atómica (tmp + rename): un lector nunca ve un archivo a medias.
    El nombre ordena por llegada: created_at compactado + id del mensaje.
    """
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    crudo = str(msg.get("created_at", ""))
    stamp = re.sub(r"[^0-9TZ]", "", crudo) or "sin-fecha"
    destino = INBOX_DIR / f"{stamp}-{msg['id']}.json"
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps(msg, indent=2, ensure_ascii=False))
    tmp.replace(destino)
    return destino


def ultimo_asunto_pendiente() -> str:
    """El asunto del hilo abierto más reciente (C3). Para la línea ABANDONO."""
    try:
        data = request("GET", "/threads", params={"status": "open"}, timeout=30)
        hilos = data.get("threads", [])
        if hilos:
            return str(hilos[0].get("subject", "(sin asunto)"))
        return "(sin hilos abiertos)"
    except Exception:
        return "(desconocido: el servidor no expone hilos)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de inbox de Agent Mesh")
    parser.add_argument(
        "--watch", required=True, help="Dirección contraparte a vigilar, p. ej. pablo.general"
    )
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--idle-exit-minutes", type=float, default=30.0)
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Pausa entre ciclos (la fija el diseño, no se negocia)",
    )
    parser.add_argument("--wait", type=int, default=30, help="Segundos de long poll")
    parser.add_argument(
        "--roster-every", type=int, default=4, help="Cada cuántos ciclos se consulta el roster"
    )
    args = parser.parse_args()

    if not SESSION_FILE.exists():
        log("SESION CADUCA: corre /agent-mesh:register")
        return EXIT_GONE

    STATE_DIR.mkdir(exist_ok=True)
    STOP_FILE.unlink(missing_ok=True)  # centinela huérfano de una corrida anterior
    PID_FILE.write_text(str(os.getpid()))
    log(
        f"monitor arriba: watch={args.watch} max_hours={args.max_hours:g} "
        f"idle_exit_minutes={args.idle_exit_minutes:g} pid={os.getpid()}"
    )

    inicio = time.monotonic()
    ultima_vida = time.monotonic()  # la cuenta de abandono empieza al arrancar
    pausa = args.interval
    ciclo = 0

    try:
        while True:
            if STOP_FILE.exists():
                log("STOP: centinela encontrado; salida limpia")
                return EXIT_STOP
            if time.monotonic() - inicio > args.max_hours * 3600:
                log(f"TOPE: {args.max_hours:g} horas cumplidas")
                return EXIT_MAXHOURS

            try:
                data = request(
                    "GET", "/inbox", params={"wait": args.wait}, timeout=args.wait + 15
                )
                pausa = args.interval  # una respuesta sana resetea el backoff
            except urllib.error.HTTPError as exc:
                if exc.code == 410:
                    log("SESION CADUCA: corre /agent-mesh:register")
                    return EXIT_GONE
                if exc.code == 429:
                    pausa = min(pausa * 2, 60.0)
                    log(f"429: pausa ampliada a {pausa:.0f}s")
                else:
                    log(
                        f"HTTP {exc.code} en inbox: {exc.read().decode(errors='replace')[:200]}"
                    )
                data = {"messages": []}
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                log(f"sin conexión: {exc}")
                data = {"messages": []}

            for msg in data.get("messages", []):
                ruta = persist(msg)  # 1. persistir
                log(  # 2. registrar
                    f"mensaje {msg['id']} from={msg.get('from')} kind={msg.get('kind')} "
                    f"subject={msg.get('subject')!r} thread={msg.get('thread_id')} "
                    f"-> {ruta.name}"
                )
                try:  # 3. solo entonces, acusar
                    request("POST", f"/messages/{msg['id']}/ack", timeout=30)
                except urllib.error.HTTPError as exc:
                    if exc.code == 410:
                        log("SESION CADUCA: corre /agent-mesh:register")
                        return EXIT_GONE
                    log(
                        f"ack de {msg['id']} falló con HTTP {exc.code}; el mensaje "
                        f"volverá a circular y el archivo ya está en disco"
                    )
            contexto = data.get("context")
            if contexto:
                log(f"contexto: {contexto.get('open_threads')} hilos abiertos")

            ciclo += 1
            if ciclo % max(args.roster_every, 1) == 0:
                try:
                    roster = request(
                        "GET", f"/projects/{_session()['project']}/roster", timeout=30
                    )
                    vivas = {s.get("address") for s in roster.get("sessions", [])}
                    if args.watch in vivas:
                        ultima_vida = time.monotonic()
                except urllib.error.HTTPError as exc:
                    if exc.code == 410:
                        log("SESION CADUCA: corre /agent-mesh:register")
                        return EXIT_GONE
                    log(f"HTTP {exc.code} en roster")
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    log(f"sin conexión al roster: {exc}")
                if time.monotonic() - ultima_vida > args.idle_exit_minutes * 60:
                    log(
                        f"ABANDONO: esperaba a {args.watch}; "
                        f"último asunto pendiente: {ultimo_asunto_pendiente()}"
                    )
                    return EXIT_ABANDON

            time.sleep(pausa)
    finally:
        PID_FILE.unlink(missing_ok=True)
        STOP_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
