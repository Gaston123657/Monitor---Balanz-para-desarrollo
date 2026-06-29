"""Captura diaria del snapshot de mercado al store histórico — SIN abrir el monitor.

Corre en el ENTORNO PRINCIPAL (py 3.12), pensado para Windows Task Scheduler:

    py -3.12 scripts/capture_daily_snapshot.py        (o capture_daily.bat)

POR QUÉ EXISTE
--------------
La captura "forward" del web server (apps/web/server.py) solo persiste si el server
está corriendo y flushea en el rollover de fecha / shutdown. Si el monitor no se abre
un día hábil, ese día se PIERDE (y no hay fuente para backfillearlo después — ver
HISTORICO-BACKFILL-FASE2.txt, sección ONs). Este script registra el snapshot del día
de forma INDEPENDIENTE del web server, para que el histórico (en especial el de ONs,
que solo se construye hacia adelante) no tenga huecos.

QUÉ HACE
--------
Reusa EXACTAMENTE la maquinaria del server (cero matemática nueva, mismas escalas y
paneles): arma el _RefreshContext, corre _refresh_bond_panels (que computa todos los
paneles de bonos y bufferea las filas vía _history_capture) y hace _history_flush()
para persistir en core/infrastructure/history_store.py con source="live". El upsert es
idempotente por (fecha, ticker): si el web server también capturó hoy, conviven sin
pisarse (la última escritura = cierre gana).

Solo escribe en días hábiles BYMA (core.holiday_engine.is_habil); en fin de semana /
feriado loguea y sale 0 (para que la tarea agendada no marque error).

Idealmente agendarlo DESPUÉS del cierre (~18:30 ART) para capturar precios de cierre.
"""
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.holiday_engine import is_habil

logger = logging.getLogger("capture_daily")


def main() -> int:
    today = date.today()
    if not is_habil(today):
        print(f"[{today}] no es día hábil BYMA — no se captura (exit 0).")
        return 0

    # Import diferido: arma providers, logging, etc. del server.
    from apps.web import server

    ctx = server._build_refresh_context()
    snapshot = server.Snapshot()

    # Computa todos los paneles de bonos y bufferea las filas del día (idéntico al
    # ciclo del server). Internamente llama _history_capture(today_str, panel, rows).
    server._refresh_bond_panels(ctx, snapshot, today)

    # Resumen por panel ANTES del flush (el buffer se vacía al flushear).
    with server._history_buffer_lock:
        from collections import Counter
        by_panel = Counter(r.get("panel") for r in server._history_buffer.values())
        total = len(server._history_buffer)

    if total == 0:
        print(f"[{today}] ADVERTENCIA: 0 filas capturadas (¿Data912 caído?). No se flushea.")
        return 1

    # Persiste el snapshot del día en el store (solo si is_habil, que ya validamos).
    server._history_flush()

    print(f"[{today}] capturado y persistido: {total} filas")
    for panel, n in sorted(by_panel.items()):
        print(f"    {panel:13s} {n}")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        logger.exception("capture_daily_snapshot falló")
        rc = 2
    # Salida dura: mata daemon threads (RofexProvider WS) sin esperar backoff.
    sys.stdout.flush()
    sys.stderr.flush()
    import os
    os._exit(rc)
