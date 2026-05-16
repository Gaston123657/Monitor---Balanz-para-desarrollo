import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from config.settings import MASTER_XLSX, setup_logging
from core.domain.instrument_groups import BOPREALES, CER, DOLAR_LINKED, SOBERANOS, TASA_FIJA
from core.infrastructure.repositories import ExcelInstrumentsRepository, Data912MarketDataProvider
from core.use_cases.generate_report import GenerateMonitorReport

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(THIS_DIR, "static")

REFRESH_SEC = 30
HOST = "127.0.0.1"
PORT = 8000

setup_logging()
logger = logging.getLogger("monitor_web")

# --------------------------------------------------------------------------- #
# Helpers JSON
# --------------------------------------------------------------------------- #
def _json_default(obj):
    if isinstance(obj, (date, datetime)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)

# --------------------------------------------------------------------------- #
# Columns Definitions
# --------------------------------------------------------------------------- #
def _get_columns(monitor_id: str):
    bonares_cols = [
        {"key": "ticker", "label": "Ticker", "kind": "text"},
        {"key": "vto", "label": "Vto", "kind": "date"},
        {"key": "price", "label": "Precio", "kind": "number", "decimals": 2},
        {"key": "tir", "label": "TIR", "kind": "percent", "decimals": 2},
        {"key": "duration", "label": "MD", "kind": "number", "decimals": 2},
        {"key": "change_pct", "label": "%Día", "kind": "percent_signed", "decimals": 2},
        {"key": "volume", "label": "Vol $", "kind": "volume"},
    ]
    schemas = {
        "bonares": bonares_cols,
        "bopreales": bonares_cols,
        "dolar_linked": bonares_cols,
        "cer": [
            {"key": "ticker", "label": "Ticker", "kind": "text"},
            {"key": "category", "label": "Categoría", "kind": "text"},
            {"key": "vto", "label": "Vto", "kind": "date"},
            {"key": "price", "label": "Precio", "kind": "number", "decimals": 2},
            {"key": "tir", "label": "TIR", "kind": "percent", "decimals": 2},
            {"key": "duration", "label": "DM", "kind": "number", "decimals": 2},
            {"key": "change_pct", "label": "Var%", "kind": "percent_signed", "decimals": 2},
            {"key": "volume", "label": "Vol $", "kind": "volume"},
        ],
        "tasa_fija": [
            {"key": "ticker", "label": "Ticker", "kind": "text"},
            {"key": "dias", "label": "Días", "kind": "number", "decimals": 0},
            {"key": "price", "label": "Precio", "kind": "number", "decimals": 2},
            {"key": "tir", "label": "TEA %", "kind": "percent", "decimals": 2},
            {"key": "change_pct", "label": "Var %", "kind": "percent_signed", "decimals": 2},
            {"key": "volume", "label": "Vol $", "kind": "volume"},
        ],
    }
    return schemas.get(monitor_id, [])

# --------------------------------------------------------------------------- #
# Snapshot & Loop
# --------------------------------------------------------------------------- #
class Snapshot:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "ts": None,
            "fx": {},
            "monitors": [
                {"id": "bonares", "title": "BONARES Y GLOBALES", "status": "loading", "rows": [], "columns": _get_columns("bonares")},
                {"id": "bopreales", "title": "BOPREALES", "status": "loading", "rows": [], "columns": _get_columns("bopreales")},
                {"id": "cer", "title": "BONOS CER", "status": "loading", "rows": [], "columns": _get_columns("cer")},
                {"id": "tasa_fija", "title": "TASA FIJA", "status": "loading", "rows": [], "columns": _get_columns("tasa_fija")},
                {"id": "dolar_linked", "title": "DOLAR LINKED", "status": "loading", "rows": [], "columns": _get_columns("dolar_linked")},
            ],
        }

    def get(self):
        with self._lock:
            return json.loads(json.dumps(self._data, default=_json_default))

    def update_monitor(self, mid, **fields):
        with self._lock:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for m in self._data["monitors"]:
                if m["id"] == mid:
                    m.update(fields)
                    m["ts"] = now
                    break
            self._data["ts"] = now

    def update_fx(self, fx_dict):
        with self._lock:
            self._data["fx"] = fx_dict
            self._data["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

def _refresh_loop(snapshot: Snapshot):
    from core.infrastructure.fx_provider import DolarAPIProvider
    repo = ExcelInstrumentsRepository(MASTER_XLSX)
    provider = Data912MarketDataProvider()
    use_case = GenerateMonitorReport(repo, provider)
    fx = DolarAPIProvider()
    
    # Backend returns TIR and variance_* as decimal fractions (0.0131 = 1.31%).
    # The web JS formatter renders the raw value with a "%" suffix, so we
    # scale those fields to percentage units here. change_pct from Data912
    # is already in percent units and must NOT be scaled.
    def _scale(v):
        return v * 100 if v is not None else None

    while True:
        try:
            snapshot.update_fx(fx.get_all())

            # Bonares
            m_bonares = use_case.execute(SOBERANOS)
            rows_bonares = []
            for m in m_bonares:
                rows_bonares.append({
                    "ticker": m.snapshot.instrument.ticker,
                    "vto": m.snapshot.instrument.maturity_date,
                    "price": m.snapshot.price,
                    "tir": _scale(m.tir),
                    "duration": m.duration,
                    "change_pct": m.snapshot.change_pct,
                    "volume": m.snapshot.volume,
                })
            snapshot.update_monitor("bonares", rows=rows_bonares, status="ok")

            # CER
            m_cer = use_case.execute(CER)
            rows_cer = []
            for m in m_cer:
                rows_cer.append({
                    "ticker": m.snapshot.instrument.ticker,
                    "category": m.snapshot.instrument.category,
                    "vto": m.snapshot.instrument.maturity_date,
                    "price": m.snapshot.price,
                    "tir": _scale(m.tir),
                    "duration": m.duration,
                    "change_pct": m.snapshot.change_pct,
                    "volume": m.snapshot.volume,
                })
            snapshot.update_monitor("cer", rows=rows_cer, status="ok")

            # Bopreales
            m_bop = use_case.execute(BOPREALES)
            rows_bop = []
            for m in m_bop:
                rows_bop.append({
                    "ticker": m.snapshot.instrument.ticker,
                    "vto": m.snapshot.instrument.maturity_date,
                    "price": m.snapshot.price,
                    "tir": _scale(m.tir),
                    "duration": m.duration,
                    "change_pct": m.snapshot.change_pct,
                    "volume": m.snapshot.volume,
                })
            snapshot.update_monitor("bopreales", rows=rows_bop, status="ok")

            # Tasa Fija
            m_fija = use_case.execute(TASA_FIJA)
            rows_fija = []
            for m in m_fija:
                vto = m.snapshot.instrument.maturity_date
                dias = (vto - date.today()).days if vto else 0
                rows_fija.append({
                    "ticker": m.snapshot.instrument.ticker,
                    "dias": dias,
                    "price": m.snapshot.price,
                    "tir": _scale(m.tir),
                    "change_pct": m.snapshot.change_pct,
                    "volume": m.snapshot.volume,
                })
            snapshot.update_monitor("tasa_fija", rows=rows_fija, status="ok")

            # Dolar Linked
            m_dl = use_case.execute(DOLAR_LINKED)
            rows_dl = []
            for m in m_dl:
                rows_dl.append({
                    "ticker": m.snapshot.instrument.ticker,
                    "vto": m.snapshot.instrument.maturity_date,
                    "price": m.snapshot.price,
                    "tir": _scale(m.tir),
                    "duration": m.duration,
                    "change_pct": m.snapshot.change_pct,
                    "volume": m.snapshot.volume,
                })
            snapshot.update_monitor("dolar_linked", rows=rows_dl, status="ok")

        except Exception as e:
            logger.error(f"Error in web refresh loop: {e}")
            
        time.sleep(REFRESH_SEC)

# --------------------------------------------------------------------------- #
# HTTP Handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    snapshot = None
    def log_message(self, fmt, *args): pass
    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/snapshot":
            payload = json.dumps(self.snapshot.get(), default=_json_default).encode("utf-8")
            return self._send(HTTPStatus.OK, payload, "application/json; charset=utf-8")
        if path in ("/", "/index.html"): return self._serve_static("index.html")
        if path.startswith("/static/"): return self._serve_static(path[len("/static/"):])
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
    def _serve_static(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        ext = os.path.splitext(full)[1].lower()
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".png": "image/png"}.get(ext, "application/octet-stream")
        with open(full, "rb") as f: self._send(HTTPStatus.OK, f.read(), ctype)

def main():
    logger.info("Starting Web Server...")
    snapshot = Snapshot()
    Handler.snapshot = snapshot
    threading.Thread(target=_refresh_loop, args=(snapshot,), daemon=True).start()
    
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info(f"Web Server running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
