"""Pruebas de las piezas puras de monitor.py.

El bucle completo se prueba en la aceptación manual (`plugin/ACEPTACION.md`);
aquí, lo que no necesita servidor: la persistencia atómica —el paso 1 del orden
sagrado persistir → registrar → acusar— y el contrato de códigos de salida que
`stop.md` y el comando `monitor` citan.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

RUTA_MONITOR = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "monitor.py"


def _carga_monitor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Importa monitor.py con cwd en un directorio temporal.

    El módulo fija sus rutas de estado a partir de `Path.cwd()` al importarse,
    igual que mesh.py, así que el chdir tiene que ocurrir antes del import.
    """
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("monitor_bajo_prueba", RUTA_MONITOR)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["monitor_bajo_prueba"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_persist_escribe_el_payload_integro_con_nombre_ordenable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _carga_monitor(tmp_path, monkeypatch)
    mensaje = {
        "id": "msg_abc123",
        "thread_id": "thr_x",
        "from": "pablo.general",
        "kind": "question",
        "subject": "¿cursor u offset?",
        "body": "…",
        "created_at": "2026-08-30T12:34:56Z",
    }

    ruta = monitor.persist(mensaje)

    assert ruta.parent == tmp_path / ".agent-mesh" / "inbox"
    assert ruta.name == "20260830T123456Z-msg_abc123.json"
    assert json.loads(ruta.read_text()) == mensaje  # íntegro, thread_id incluido
    assert not list(ruta.parent.glob("*.tmp"))  # la escritura atómica no deja residuos


def test_persist_es_estable_ante_created_at_ausente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor = _carga_monitor(tmp_path, monkeypatch)

    ruta = monitor.persist({"id": "msg_x", "subject": "s"})

    assert ruta.name == "sin-fecha-msg_x.json"
    assert ruta.exists()


def test_codigos_de_salida_del_contrato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stop.md y monitor.md citan estos códigos; cambiarlos rompe el plugin."""
    monitor = _carga_monitor(tmp_path, monkeypatch)

    assert monitor.EXIT_STOP == 0
    assert monitor.EXIT_ABANDON == 2
    assert monitor.EXIT_MAXHOURS == 3
    assert monitor.EXIT_GONE == 4


def test_sin_session_json_sale_con_codigo_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sin sesión no hay nada que sondear: el monitor no se registra solo."""
    monitor = _carga_monitor(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["monitor.py", "--watch", "pablo.general"])

    assert monitor.main() == monitor.EXIT_GONE
    assert "/agent-mesh:register" in capsys.readouterr().out
