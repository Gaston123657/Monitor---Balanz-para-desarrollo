"""USD/ARS quotes from dolarapi.com.

Architectural exception (like BCRAIndicesProvider for CER): FX reference
data is fetched from dolarapi.com which aggregates BCRA + market sources.
Used for:
  - Dolar mayorista (venta) -> deflator for DOLAR_LINKED bond TIRs
  - All quotes -> header strip in the web dashboard

Thread-safe in-process cache; refreshes once per minute.
"""

import json
import logging
import ssl
import threading
import time
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DolarAPIProvider:
    URL = "https://dolarapi.com/v1/dolares"
    TTL_SECONDS = 60

    _lock = threading.Lock()
    _cache: Dict[str, dict] = {}
    _last_fetch_ts: float = 0.0

    def _fetch(self) -> None:
        with self._lock:
            if self._cache and (time.time() - self._last_fetch_ts) < self.TTL_SECONDS:
                return
            try:
                ctx = ssl._create_unverified_context()
                req = urllib.request.Request(self.URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                    payload = json.loads(r.read().decode("utf-8"))
                fresh = {}
                for row in payload:
                    casa = str(row.get("casa", "")).strip().lower()
                    if not casa:
                        continue
                    fresh[casa] = {
                        "nombre": row.get("nombre"),
                        "compra": float(row["compra"]) if row.get("compra") else None,
                        "venta": float(row["venta"]) if row.get("venta") else None,
                        "fechaActualizacion": row.get("fechaActualizacion"),
                    }
                if fresh:
                    self._cache = fresh
                    self._last_fetch_ts = time.time()
                    logger.info(f"Loaded {len(fresh)} USD quotes from dolarapi.")
            except Exception as e:
                logger.warning(f"DolarAPI fetch failed: {e}")

    def get_all(self) -> Dict[str, dict]:
        self._fetch()
        return dict(self._cache)

    def get_quote(self, casa: str) -> Optional[dict]:
        self._fetch()
        return self._cache.get(casa.lower())

    def get_mayorista_venta(self) -> Optional[float]:
        q = self.get_quote("mayorista")
        return q.get("venta") if q else None
