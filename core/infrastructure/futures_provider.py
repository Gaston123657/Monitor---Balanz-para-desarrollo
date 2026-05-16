"""Futures market data from Matba-Rofex via pyRofex (Primary API).

Architectural exception (third allowed source outside Data912, alongside
BCRA for CER and dolarapi.com for USD/ARS): Primary's wss/REST endpoints
are the canonical feed for AR futures (DLR, RFX20, ORO, etc.).

Credentials are loaded from env vars; if missing, the provider returns an
empty dict and logs a warning — the rest of the system keeps running.
Required env vars:
  ROFEX_USER       e.g. davidberisso23342
  ROFEX_PASSWORD   the API password
  ROFEX_ACCOUNT    e.g. REM23342
  ROFEX_ENV        'remarkets' (default, demo) or 'live'

Cache: 30s in-process, thread-safe. pyRofex.initialize() is global state
so the lazy init runs only once per process.
"""

import calendar
import logging
import os
import threading
import time
from datetime import date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Spanish month abbreviations used in Matba-Rofex tickers (DLR/MAY26 etc.)
_MONTHS = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


def parse_contract_maturity(symbol: str) -> Optional[date]:
    """DLR/MAY26 -> 2026-05-31 (last calendar day of contract month)."""
    if "/" not in symbol:
        return None
    tail = symbol.split("/", 1)[1].rstrip("M").strip().upper()
    if len(tail) < 5:
        return None
    mon, yy = tail[:3], tail[3:5]
    if mon not in _MONTHS or not yy.isdigit():
        return None
    year = 2000 + int(yy)
    month = _MONTHS[mon]
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def implied_tna(future_price: float, spot: float, mat: date, today: Optional[date] = None) -> Optional[float]:
    """TNA implícita = (futuro/spot)^(365/days) - 1, decimal fraction."""
    if not (future_price and spot and spot > 0 and mat):
        return None
    today = today or date.today()
    days = (mat - today).days
    if days <= 0:
        return None
    try:
        return (future_price / spot) ** (365 / days) - 1
    except (ValueError, ZeroDivisionError, OverflowError):
        return None

# Spot reference Matba publishes for DLR settlement. Used as the canonical
# spot for TNA implícita — same number Matba uses to liquidate the futures.
SPOT_SYMBOL = "DLR/SPOT"

# Default universe: full curve of Dolar futuro (DLR) — all monthly contracts
# from front month out to ~12 months ahead.
DEFAULT_SYMBOLS: List[str] = [
    "DLR/MAY26", "DLR/JUN26", "DLR/JUL26", "DLR/AGO26", "DLR/SEP26",
    "DLR/OCT26", "DLR/NOV26", "DLR/DIC26",
    "DLR/ENE27", "DLR/FEB27", "DLR/MAR27", "DLR/ABR27",
]


class RofexProvider:
    TTL_SECONDS = 30

    _lock = threading.Lock()
    _initialized: bool = False
    _init_failed: bool = False
    _cache: Dict[str, dict] = {}
    _last_fetch_ts: float = 0.0

    def _initialize(self) -> bool:
        """One-time pyRofex.initialize. Returns True on success."""
        if self._initialized:
            return True
        if self._init_failed:
            return False

        user = os.environ.get("ROFEX_USER")
        pwd = os.environ.get("ROFEX_PASSWORD")
        acc = os.environ.get("ROFEX_ACCOUNT")
        env_name = os.environ.get("ROFEX_ENV", "remarkets").lower()

        if not (user and pwd and acc):
            logger.warning(
                "Rofex credentials missing (set ROFEX_USER/ROFEX_PASSWORD/"
                "ROFEX_ACCOUNT env vars to enable futures monitor)."
            )
            self._init_failed = True
            return False

        try:
            import pyRofex
            env = pyRofex.Environment.LIVE if env_name == "live" else pyRofex.Environment.REMARKET
            pyRofex.initialize(user=user, password=pwd, account=acc, environment=env)
            self._initialized = True
            logger.info(f"Rofex initialized in {env_name} mode for account {acc}.")
            return True
        except Exception as e:
            logger.warning(f"Rofex initialize failed: {e}")
            self._init_failed = True
            return False

    def _fetch(self, symbols: List[str]) -> None:
        if not self._initialize():
            return
        try:
            import pyRofex
            entries = [
                pyRofex.MarketDataEntry.LAST,
                pyRofex.MarketDataEntry.BIDS,
                pyRofex.MarketDataEntry.OFFERS,
                pyRofex.MarketDataEntry.SETTLEMENT_PRICE,
                pyRofex.MarketDataEntry.TRADE_VOLUME,
                pyRofex.MarketDataEntry.OPEN_INTEREST,
            ]
            fresh: Dict[str, dict] = {}
            for sym in symbols:
                try:
                    md = pyRofex.get_market_data(sym, entries=entries)
                    if md.get("status") != "OK":
                        continue
                    d = md.get("marketData", {})
                    oi = d.get("OI")
                    oi_size = (oi.get("size") if isinstance(oi, dict) else None) if oi else None
                    fresh[sym] = {
                        "last": d.get("LA", {}).get("price") if d.get("LA") else None,
                        "bid": d.get("BI", [{}])[0].get("price") if d.get("BI") else None,
                        "ask": d.get("OF", [{}])[0].get("price") if d.get("OF") else None,
                        "settle": d.get("SE", {}).get("price") if d.get("SE") else None,
                        "volume": d.get("TV"),
                        "open_interest": oi_size,
                    }
                except Exception as e:
                    logger.debug(f"Rofex md fail {sym}: {e}")
            if fresh:
                self._cache = fresh
                self._last_fetch_ts = time.time()
        except Exception as e:
            logger.warning(f"Rofex fetch failed: {e}")

    def get_quotes(self, symbols: Optional[List[str]] = None) -> Dict[str, dict]:
        if symbols is None:
            symbols = DEFAULT_SYMBOLS
        with self._lock:
            stale = (time.time() - self._last_fetch_ts) >= self.TTL_SECONDS
            if not self._cache or stale:
                self._fetch(symbols)
            return dict(self._cache)
