"""BCRA reference indices (CER, TAMAR).

Architectural exception: market data must come from Data912, but BCRA
publishes reference series only available from its own API.

Variables fetched (BCRA `Monetarias/{id}`):
  - 30: CER (Coeficiente de Estabilización de Referencia) — daily index level
  - 44: Tasa de interés TAMAR de bancos privados (TNA %)
"""

import json
import logging
import ssl
import threading
import urllib.request
from datetime import date, datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


_BCRA_BASE = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"


def _fetch_series(variable_id: int, days: int = 60) -> Dict[date, float]:
    """Pull last `days` days of a BCRA monetary variable."""
    end = date.today()
    start = end - timedelta(days=days)
    url = f"{_BCRA_BASE}/{variable_id}?Desde={start}&Hasta={end}"
    ctx = ssl._create_unverified_context()
    out: Dict[date, float] = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            payload = json.loads(r.read().decode("utf-8"))
        results = payload.get("results", [])
        if results and "detalle" in results[0]:
            for item in results[0]["detalle"]:
                try:
                    d = datetime.strptime(item["fecha"], "%Y-%m-%d").date()
                    out[d] = float(item["valor"])
                except (KeyError, ValueError, TypeError):
                    continue
    except Exception as e:
        logger.warning(f"BCRA fetch failed for variable {variable_id}: {e}")
    return out


class BCRAIndicesProvider:
    """CER + TAMAR from BCRA, with per-day in-memory cache."""

    _lock = threading.Lock()
    _cache_cer: Dict[date, float] = {}
    _cache_tamar: Dict[date, float] = {}
    _last_attempt: Optional[date] = None

    def __init__(self, excel_repo=None):
        self.excel_repo = excel_repo

    def _fetch_all(self):
        with self._lock:
            if self._cache_cer and self._last_attempt == date.today():
                return
            self._last_attempt = date.today()

            cer = _fetch_series(30, days=60)
            if cer:
                self._cache_cer = cer
                logger.info(f"Loaded {len(cer)} CER points from BCRA.")

            # TAMAR needs deep history for bonds emitted up to ~2 years ago
            # (TTJ26 was issued 2025-01-29). Pull 3 years to be safe.
            tamar = _fetch_series(44, days=3 * 365)
            if tamar:
                self._cache_tamar = tamar
                logger.info(f"Loaded {len(tamar)} TAMAR points from BCRA.")

    @staticmethod
    def _lookup(target: date, cache: Dict[date, float]) -> Optional[float]:
        if not cache:
            return None
        if target in cache:
            return cache[target]
        for i in range(1, 15):
            prev = target - timedelta(days=i)
            if prev in cache:
                return cache[prev]
        return cache[max(cache.keys())]

    def get_cer(self, target_date: date) -> Optional[float]:
        self._fetch_all()
        return self._lookup(target_date, self._cache_cer)

    def get_tamar(self, target_date: Optional[date] = None) -> Optional[float]:
        """TAMAR TNA (%) — annualized nominal rate published by BCRA.
        Returns the rate at `target_date` (defaults to today, with 14-day
        backward search if the exact date is missing from the series).
        """
        self._fetch_all()
        return self._lookup(target_date or date.today(), self._cache_tamar)
