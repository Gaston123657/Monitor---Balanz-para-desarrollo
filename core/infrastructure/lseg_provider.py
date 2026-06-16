"""LSEG Workspace / Eikon Data API — cliente genérico.

Excepción arquitectónica (como RofexProvider con su WebSocket): la conexión la
gestiona el SDK de vendor `lseg-data`, no pasa por `_http.py`. No es un fetch de
precios crudos vía requests, es la librería oficial de LSEG.

Modo **Desktop Session**: la librería NO sale directo a internet. Habla con un
proxy local (handshake contra http://localhost:9000) que levanta **LSEG Workspace
mientras está abierto y logueado en ESTA MISMA máquina**. Sin Workspace corriendo
no hay dato. El App Key (LSEG_APP_KEY en .env) es la credencial.

Diseño genérico a propósito (`get_data` / `get_history`): esta fase deja la API
enlazada y verificada para cualquier dato que requiera la evolución del monitor
(precios internacionales, reference data, históricos, FX/tasas). Todavía NO se
enchufa a paneles ni implementa IMarketDataProvider — eso vendrá cuando se integre
una fuente concreta.

Sesión única por proceso: cacheada a nivel de clase y protegida con lock. Abrir una
Desktop Session es caro (handshake) y Workspace admite una sola por app key.

ENTORNO: `lseg-data` exige pandas<3 y choca con el monitor (pandas==3.0.3). Por eso
el SDK vive en un venv AISLADO (.venv-lseg, ver requirements-lseg.txt), no en el
entorno principal. En el entorno del monitor `is_available()` devuelve False (el
import del SDK falla, manejado con LSEGConfigError) — degrada elegante sin romper.
Cuando se integre a un panel habrá que puentear ambos entornos (subproceso/IPC).
"""

import logging
import os
import threading
from typing import List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

APP_KEY_ENV = "LSEG_APP_KEY"


class LSEGError(Exception):
    """Error base del provider LSEG."""


class LSEGConfigError(LSEGError):
    """Falta configuración (p. ej. LSEG_APP_KEY) o no está instalado el SDK."""


class LSEGConnectionError(LSEGError):
    """No se pudo abrir la sesión (Workspace cerrado / handshake falló / key inválida)."""


class LSEGWorkspaceProvider:
    """Wrapper fino sobre `lseg.data` con Desktop Session.

    Uso típico:
        p = LSEGWorkspaceProvider()
        if p.is_available():
            df = p.get_data("EUR=", ["BID", "ASK"])
    """

    _lock = threading.Lock()
    _session = None          # sesión `lseg.data` abierta (compartida por proceso)
    _open = False            # True si la sesión está abierta y lista

    # ------------------------------------------------------------------ config
    @staticmethod
    def _app_key() -> str:
        key = (os.environ.get(APP_KEY_ENV) or "").strip()
        if not key:
            raise LSEGConfigError(
                f"Falta {APP_KEY_ENV}. Copiá .env.example a .env y completá el App Key "
                f"del AppKey Generator de LSEG Workspace."
            )
        return key

    @staticmethod
    def _import_lib():
        try:
            import lseg.data as ld  # noqa: PLC0415 (import lazy: el SDK es pesado)
            return ld
        except ImportError as e:
            raise LSEGConfigError(
                "No está instalado el SDK `lseg-data`. Corré "
                "`pip install -r requirements.txt`."
            ) from e

    # ------------------------------------------------------------- ciclo de vida
    def open(self):
        """Abre la Desktop Session (idempotente, lazy, thread-safe).

        Lanza LSEGConfigError si falta el app key / SDK, o LSEGConnectionError si
        Workspace no está corriendo o el handshake falla.
        """
        with self._lock:
            if type(self)._open and type(self)._session is not None:
                return type(self)._session

            ld = self._import_lib()
            app_key = self._app_key()
            try:
                session = ld.session.desktop.Definition(app_key=app_key).get_session()
                ld.session.set_default(session)
                session.open()
            except LSEGError:
                raise
            except Exception as e:
                raise LSEGConnectionError(
                    "No se pudo abrir la Desktop Session de LSEG. Verificá que LSEG "
                    "Workspace esté ABIERTO y LOGUEADO en esta máquina (handshake "
                    f"localhost:9000) y que el App Key sea válido. Detalle: "
                    f"{type(e).__name__}: {e}"
                ) from e

            type(self)._session = session
            type(self)._open = True
            logger.info("LSEG Desktop Session abierta (Workspace local).")
            return session

    def close(self) -> None:
        with self._lock:
            if type(self)._session is not None:
                try:
                    type(self)._session.close()
                except Exception as e:
                    logger.warning(f"Error cerrando sesión LSEG: {e}")
            type(self)._session = None
            type(self)._open = False

    def is_available(self) -> bool:
        """True si la sesión se puede abrir (Workspace corriendo + key OK).

        No lanza: pensado para que el resto del código degrade elegante cuando
        Workspace no está disponible.
        """
        try:
            self.open()
            return True
        except LSEGError as e:
            logger.warning(f"LSEG no disponible: {e}")
            return False

    # --------------------------------------------------------------- consultas
    def get_data(self,
                 universe: Union[str, Sequence[str]],
                 fields: Optional[List[str]] = None):
        """Snapshot de campos para uno o varios instrumentos (RICs).

        Envuelve `ld.get_data`. Devuelve un pandas.DataFrame.
        Ej: get_data("EUR=", ["BID", "ASK"]) / get_data(["AAPL.O","MSFT.O"], ["TR.PriceClose"])
        """
        ld = self._import_lib()
        self.open()
        return ld.get_data(universe=universe, fields=fields)

    def get_history(self,
                    universe: Union[str, Sequence[str]],
                    fields: Optional[List[str]] = None,
                    interval: Optional[str] = None,
                    start=None,
                    end=None,
                    count: Optional[int] = None):
        """Serie histórica / time series. Envuelve `ld.get_history`.

        Devuelve un pandas.DataFrame. `interval` p. ej. "daily", "1min".
        """
        ld = self._import_lib()
        self.open()
        kwargs = {"universe": universe}
        if fields is not None:
            kwargs["fields"] = fields
        if interval is not None:
            kwargs["interval"] = interval
        if start is not None:
            kwargs["start"] = start
        if end is not None:
            kwargs["end"] = end
        if count is not None:
            kwargs["count"] = count
        return ld.get_history(**kwargs)
