import urllib.request
import json
import ssl
import logging
import threading
from datetime import date, datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class BCRAIndicesProvider:
    """CER reference index from BCRA (api.bcra.gob.ar).

    Architectural exception: market data must come from Data912, but the CER
    coefficient is published only by the BCRA (Argentine Central Bank). It is
    reference data, not price data — used to compute real TIR and technical
    value for CER-indexed bonds. This is the ONLY allowed external source
    outside Data912 in the system.
    """
    BCRA_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/30"
    
    _lock = threading.Lock()
    _instance_cache: Dict[date, float] = {}
    _last_attempt: Optional[date] = None
    _failed_recently = False

    def __init__(self, excel_repo=None):
        self.excel_repo = excel_repo

    def _fetch_all(self):
        with self._lock:
            if self._instance_cache and self._last_attempt == date.today():
                return

            self._last_attempt = date.today()
            data_map = {}
            ctx = ssl._create_unverified_context()
            
            try:
                # Try BCRA with correct parameter casing: Desde and Hasta
                # Range from 60 days ago to today
                end_date = date.today()
                start_date = end_date - timedelta(days=60)
                url = f"{self.BCRA_URL}?Desde={start_date}&Hasta={end_date}"
                
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                    payload = json.loads(r.read().decode("utf-8"))
                    # In v4.0, data is inside results[0]["detalle"]
                    results = payload.get("results", [])
                    if results and "detalle" in results[0]:
                        items = results[0]["detalle"]
                        for item in items:
                            try:
                                d = datetime.strptime(item["fecha"], "%Y-%m-%d").date()
                                data_map[d] = float(item["valor"])
                            except (KeyError, ValueError, TypeError):
                                continue

                if data_map:
                    logger.info(f"Successfully loaded {len(data_map)} CER points from official BCRA API.")
                    self._instance_cache = data_map
                    self._failed_recently = False
                    return
            except Exception as e:
                if not self._failed_recently:
                    logger.warning(f"BCRA API connection error: {e}")

            self._failed_recently = True

    def get_cer(self, target_date: date) -> Optional[float]:
        self._fetch_all()
        
        if target_date in self._instance_cache:
            return self._instance_cache[target_date]
        
        # Search backwards (up to 15 days)
        for i in range(1, 15):
            prev = target_date - timedelta(days=i)
            if prev in self._instance_cache:
                return self._instance_cache[prev]
        
        # Final fallback: last known value
        if self._instance_cache:
            return self._instance_cache[max(self._instance_cache.keys())]
            
        return None
