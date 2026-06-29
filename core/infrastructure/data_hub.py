"""DataHub — facade / router único de fuentes de datos del monitor.

Punto único que decide "qué fuente sirve qué dato" y degrada elegante cuando una
no está disponible. Reemplaza el acoplamiento directo a un solo provider en
`apps/web/server.py::_build_refresh_context`.

Diseño:
- **Precios = Data912, siempre (Pilar 4).** El hub implementa `IMarketDataProvider`
  delegando `fetch_snapshots` / `fetch_historical_prices` al provider de precios
  (Data912). Cualquier otro método/atributo del provider de precios
  (`fetch_stock_history`, `invalidate_cache`, ...) se delega transparente vía
  `__getattr__`, así el hub es **drop-in** donde antes iba el `Data912MarketDataProvider`.
- **Capacidades complementarias** (profundidad/order book, datos de referencia,
  índices/paneles oficiales, cierre/EOD) se enrutan a los providers registrados
  (BYMADATA, LSEG, ...) por orden de prioridad. Cada uno se gatea con
  `is_available()` (que NO lanza) y la primera respuesta no vacía gana. Si ninguno
  responde, se degrada a `None`/`{}` — nunca rompe el monitor.

Los providers complementarios NO sirven precios de panel: solo agregan lo que
Data912 no da. Mantener este invariante preserva el Pilar 4.

Las capacidades nuevas (fetch_depth/reference/indices/turnover/eod) NO se usan en
el loop de 5s; las consume código offline o endpoints puntuales. Por eso el costo
de `is_available()` por llamada (p. ej. LSEG abriendo sesión) es aceptable.
"""

import logging
from datetime import date
from typing import Dict, List, Optional

from core.domain.interfaces import IMarketDataProvider
from core.domain.models import MarketSnapshot

logger = logging.getLogger(__name__)


class DataHub(IMarketDataProvider):
    """Facade por capacidades sobre múltiples fuentes de datos.

    Uso:
        hub = DataHub(price_provider=Data912MarketDataProvider(),
                      providers=[BYMADATAProvider(), LSEGWorkspaceProvider()])
        # Precios (Pilar 4 → Data912):
        hub.fetch_snapshots([...]); hub.invalidate_cache()
        # Complementos (degradan a None/{} si no hay fuente):
        hub.fetch_depth("AL30"); hub.fetch_reference_data([...])
    """

    def __init__(self, price_provider: IMarketDataProvider, providers=None):
        # _market: única fuente de precios (Data912). Pilar 4.
        self._market = price_provider
        # _providers: fuentes complementarias, en orden de prioridad.
        self._providers = list(providers or [])

    # ------------------------------------------------ IMarketDataProvider (precios)
    def fetch_snapshots(self, tickers: List[str]) -> Dict[str, MarketSnapshot]:
        return self._market.fetch_snapshots(tickers)

    def fetch_historical_prices(self, ticker: str, days: int) -> Dict[date, float]:
        return self._market.fetch_historical_prices(ticker, days)

    def __getattr__(self, name):
        """Delegación transparente al provider de precios.

        Solo se invoca cuando el atributo NO existe en DataHub, así métodos extra
        del provider de precios (`fetch_stock_history`, `invalidate_cache`, ...)
        siguen funcionando y el hub es drop-in. Se evita recursión guardando contra
        nombres privados y el caso `_market` aún no seteado.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        market = self.__dict__.get("_market")
        if market is not None:
            try:
                return getattr(market, name)
            except AttributeError:
                pass
        raise AttributeError(name)

    # ------------------------------------------------------------- registro
    def register(self, provider) -> None:
        """Agrega un provider complementario (orden = prioridad)."""
        self._providers.append(provider)

    # ------------------------------------------------------------- routing
    def _route(self, capability: str, default, *args, **kwargs):
        """Intenta cada provider complementario en orden; primera respuesta no
        vacía gana. Gatea con is_available() y captura errores → degrada a default.
        """
        for p in self._providers:
            method = getattr(p, capability, None)
            if method is None or not callable(method):
                continue
            try:
                avail = p.is_available()
            except Exception as e:  # is_available NO debería lanzar, pero por las dudas
                logger.warning("DataHub: %s.is_available() lanzó: %s", type(p).__name__, e)
                continue
            if not avail:
                continue
            try:
                result = method(*args, **kwargs)
            except Exception as e:
                logger.warning("DataHub: %s.%s falló: %s: %s",
                               type(p).__name__, capability, type(e).__name__, e)
                continue
            if result:  # no vacío (None / {} / [] → seguir probando)
                logger.debug("DataHub: '%s' servido por %s", capability, type(p).__name__)
                return result
        return default

    # ---------------------------------------------------------- capacidades
    def fetch_depth(self, ticker: str) -> Optional[dict]:
        """Profundidad / order book (puntas por nivel). None si no hay fuente."""
        return self._route("fetch_depth", None, ticker)

    def fetch_reference_data(self, tickers: List[str]) -> dict:
        """Datos de referencia (vto, cupones, ISIN, amortizaciones). {} si no hay fuente."""
        return self._route("fetch_reference_data", {}, tickers)

    def fetch_indices(self) -> dict:
        """Índices y paneles oficiales BYMA. {} si no hay fuente."""
        return self._route("fetch_indices", {})

    def fetch_turnover(self) -> dict:
        """Volúmenes / turnover agregado oficial. {} si no hay fuente."""
        return self._route("fetch_turnover", {})

    def fetch_eod(self, *args, **kwargs) -> dict:
        """Cierre oficial / end-of-day. {} si no hay fuente."""
        return self._route("fetch_eod", {}, *args, **kwargs)

    # ------------------------------------------------------------ introspección
    def available_sources(self) -> List[str]:
        """Nombres de providers complementarios actualmente disponibles (diagnóstico)."""
        out = []
        for p in self._providers:
            try:
                if p.is_available():
                    out.append(type(p).__name__)
            except Exception:
                pass
        return out
