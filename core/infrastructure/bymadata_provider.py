"""BYMADATA — provider complementario para el DataHub.

Aporta lo que Data912 no da: profundidad/order book, datos de referencia, índices y
paneles oficiales, cierre/EOD. **No sirve precios de panel** (Pilar 4: precios = Data912).

Patrón LSEG: lazy, `is_available()` que NO lanza, excepciones tipadas, credenciales
desde `.env` (cargado por `config/settings.py::_load_dotenv`). Degrada elegante: si no
está configurado/disponible, el DataHub lo saltea y no rompe nada.

Dos modos (env `BYMADATA_MODE`):

  - `rest`  — API REST oficial (`api-mgr.byma.com.ar`, OAuth2 client_credentials).
              Requiere `BYMADATA_CLIENT_ID` / `BYMADATA_CLIENT_SECRET` de una app del
              portal de desarrolladores (producto distinto del Add-in de Excel).
              Pasa por `_http.py::http_get_json` (retry sobre transients). Hoy queda
              **inerte** salvo que existan esas credenciales.

  - `excel` — Puente COM contra Excel con el **Add-in de Excel de BYMADATA** cargado y
              logueado (login usuario/password). Lee valores de un workbook con UDFs
              BYMA vía `xlwings`. Desktop-only y frágil: sirve para enriquecimiento
              periódico/offline, NO para el loop de 5s. `xlwings` vive en
              `requirements-bymadata.txt` (import lazy, no en el entorno principal).

  - vacío / `off` — provider deshabilitado (default). `is_available()` → False.

IMPORTANTE — estado de mapeo: el spike (`scripts/bymadata_probe.py`) confirmó que el
.xll es un add-in ExcelDNA (.NET) sin endpoints en texto plano. Los paths REST exactos
y los nombres de las UDFs BYMA deben confirmarse por captura de tráfico / manual antes
de habilitar consultas reales. Mientras tanto las capacidades degradan a None/{}.
Ver `BYMADATA_EXCEL/PROBE-FINDINGS.md`.
"""

import logging
import os
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODE_ENV = "BYMADATA_MODE"
DEFAULT_BASE_URL = "https://api-mgr.byma.com.ar"


class BYMADATAError(Exception):
    """Error base del provider BYMADATA."""


class BYMADATAConfigError(BYMADATAError):
    """Falta configuración (credenciales, workbook, SDK) o modo no soportado."""


class BYMADATAConnectionError(BYMADATAError):
    """No se pudo conectar (token inválido, Excel/Add-in no disponible, etc.)."""


class BYMADATAProvider:
    """Provider complementario BYMADATA (modos `rest` / `excel`).

    Uso (vía DataHub):
        p = BYMADATAProvider()
        if p.is_available():
            p.fetch_reference_data(["AL30", "GD30"])
    """

    _lock = threading.Lock()
    _token = None            # (access_token, expira_epoch) cacheado a nivel de clase (modo rest)
    _xl_book = None          # workbook xlwings abierto (modo excel)

    # ------------------------------------------------------------------ config
    @staticmethod
    def _mode() -> str:
        return (os.environ.get(MODE_ENV) or "").strip().lower()

    @staticmethod
    def _base_url() -> str:
        return (os.environ.get("BYMADATA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    @staticmethod
    def _rest_creds():
        cid = (os.environ.get("BYMADATA_CLIENT_ID") or "").strip()
        secret = (os.environ.get("BYMADATA_CLIENT_SECRET") or "").strip()
        return cid, secret

    # ------------------------------------------------------------- disponibilidad
    def is_available(self) -> bool:
        """True si el provider está configurado y operable. NO lanza.

        - `rest`: hay client_id + client_secret (token se valida lazy en la 1ª llamada).
        - `excel`: hay un workbook configurado y `xlwings` importable.
        - otro: deshabilitado.
        """
        mode = self._mode()
        try:
            if mode == "rest":
                cid, secret = self._rest_creds()
                if not (cid and secret):
                    logger.debug("BYMADATA rest: faltan BYMADATA_CLIENT_ID/SECRET.")
                    return False
                return True
            if mode == "excel":
                if not (os.environ.get("BYMADATA_WORKBOOK") or "").strip():
                    logger.debug("BYMADATA excel: falta BYMADATA_WORKBOOK.")
                    return False
                self._import_xlwings()  # lanza BYMADATAConfigError si no está
                return True
            return False
        except BYMADATAError as e:
            logger.warning("BYMADATA no disponible: %s", e)
            return False

    # ------------------------------------------------------------- modo REST
    @staticmethod
    def _import_requests_helper():
        # Reutiliza el cliente HTTP unificado del monitor (retry sobre transients).
        from core.infrastructure._http import http_get_json  # noqa: PLC0415
        return http_get_json

    def _get_token(self) -> str:
        """Devuelve un access_token válido (client_credentials), cacheado por clase.

        NOTA: el path/forma exactos del endpoint de token dependen del portal de BYMA;
        se parametriza por `BYMADATA_TOKEN_URL` (default `<base>/token`). Confirmar
        contra el portal/Postman antes de uso productivo.
        """
        import requests  # noqa: PLC0415 (ya es dependencia del monitor)
        with self._lock:
            tok = type(self)._token
            now = time.time()
            if tok and tok[1] - 30 > now:
                return tok[0]
            cid, secret = self._rest_creds()
            if not (cid and secret):
                raise BYMADATAConfigError("Faltan BYMADATA_CLIENT_ID/BYMADATA_CLIENT_SECRET.")
            token_url = (os.environ.get("BYMADATA_TOKEN_URL")
                         or f"{self._base_url()}/token")
            try:
                resp = requests.post(
                    token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(cid, secret),
                    timeout=10,
                    verify=False,
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as e:
                raise BYMADATAConnectionError(
                    f"No se pudo obtener token de BYMADATA ({token_url}): "
                    f"{type(e).__name__}: {e}"
                ) from e
            access = payload.get("access_token")
            if not access:
                raise BYMADATAConnectionError(
                    f"Respuesta de token sin 'access_token': {payload!r}")
            expires_in = float(payload.get("expires_in", 3600))
            type(self)._token = (access, now + expires_in)
            return access

    def _rest_get(self, resource: str, params: Optional[dict] = None) -> dict:
        """GET autenticado a `<base>/<resource>`. Devuelve JSON (dict/list envuelto)."""
        http_get_json = self._import_requests_helper()
        token = self._get_token()
        url = f"{self._base_url()}/{resource.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}
        data = http_get_json(url, params=params, headers=headers)
        return data if isinstance(data, dict) else {"items": data}

    # ------------------------------------------------------------- modo EXCEL
    @staticmethod
    def _import_xlwings():
        try:
            import xlwings as xw  # noqa: PLC0415
            return xw
        except ImportError as e:
            raise BYMADATAConfigError(
                "Falta `xlwings` para el modo excel de BYMADATA. Instalá "
                "`pip install -r requirements-bymadata.txt` (Windows + Excel + Add-in)."
            ) from e

    def _excel_book(self):
        """Abre (idempotente) el workbook puente con las UDFs BYMA. Desktop-only."""
        with self._lock:
            if type(self)._xl_book is not None:
                return type(self)._xl_book
            xw = self._import_xlwings()
            path = (os.environ.get("BYMADATA_WORKBOOK") or "").strip()
            if not path:
                raise BYMADATAConfigError("Falta BYMADATA_WORKBOOK (ruta al .xlsx puente).")
            try:
                book = xw.Book(path)
            except Exception as e:
                raise BYMADATAConnectionError(
                    f"No se pudo abrir el workbook puente '{path}'. Verificá que Excel "
                    f"esté abierto con el Add-in BYMADATA cargado y logueado. "
                    f"Detalle: {type(e).__name__}: {e}"
                ) from e
            type(self)._xl_book = book
            return book

    # --------------------------------------------------------------- capacidades
    # Cada capacidad enruta al modo activo. Hasta confirmar paths/UDFs exactos
    # (post captura de tráfico / manual), devuelven None/{} → el DataHub degrada.
    def _capability(self, resource: str, params: Optional[dict] = None, default=None):
        if not self.is_available():
            return default
        mode = self._mode()
        try:
            if mode == "rest":
                return self._rest_get(resource, params) or default
            # modo excel: el mapeo capacidad→UDF se completa tras confirmar nombres.
            logger.debug("BYMADATA excel: '%s' aún sin mapear a UDF; degrada.", resource)
            return default
        except BYMADATAError as e:
            logger.warning("BYMADATA '%s' falló: %s", resource, e)
            return default

    def fetch_depth(self, ticker: str) -> Optional[dict]:
        """Profundidad / order book de un ticker."""
        return self._capability("fixed_income", {"ticker": ticker, "depth": True}, default=None)

    def fetch_reference_data(self, tickers: List[str]) -> Dict[str, dict]:
        """Datos de referencia (vto, cupones, ISIN, amortizaciones)."""
        return self._capability("fixed_income",
                                {"tickers": ",".join(tickers), "fields": "reference"},
                                default={}) or {}

    def fetch_indices(self) -> dict:
        """Índices y paneles oficiales BYMA."""
        return self._capability("indices", default={}) or {}

    def fetch_turnover(self) -> dict:
        """Volúmenes / turnover agregado oficial."""
        return self._capability("turnover", default={}) or {}

    def fetch_eod(self, group: Optional[str] = None, **kwargs) -> dict:
        """Cierre oficial / end-of-day."""
        params = {"group": group} if group else None
        return self._capability("fixed_income", params, default={}) or {}

    # ------------------------------------------------------------- ciclo de vida
    def close(self) -> None:
        with self._lock:
            book = type(self)._xl_book
            if book is not None:
                try:
                    book.app.quit()
                except Exception as e:
                    logger.warning("Error cerrando Excel BYMADATA: %s", e)
            type(self)._xl_book = None
            type(self)._token = None
