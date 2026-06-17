"""ArgentinaDatos provider — letras + riesgo país.

Letras endpoint: GET https://api.argentinadatos.com/v1/finanzas/letras
Response: [{ticker, fechaEmision, fechaVencimiento, tem, vpv}, ...]
TTL 1h — la Sec. Finanzas solo actualiza en días de licitación.

Riesgo país endpoint: GET https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais/ultimo
Response: {fecha, valor}  (valor en bps, e.g. 750)
TTL 5min — dato diario publicado por JP Morgan, actualiza 1-2x por día.

Histórico: GET https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais
TTL 1h — serie completa ordenada por fecha. Se usa para (a) el valor del día
anterior (delta diario) y (b) reconciliar contra `/ultimo`.

`/ultimo` y el histórico son dos archivos estáticos servidos por separado
(GitHub Pages) y pueden desincronizarse: uno puede traer un día más nuevo que
el otro. Para mostrar el dato MÁS FIEL del día se toma el de mayor `fecha`
entre ambos, el delta se calcula contra la entrada inmediatamente anterior por
fecha (no por posición), y se marca `stale` cuando la fecha del dato quedó más
de un día hábil atrás respecto de hoy.
"""

import logging
import threading
import time
from typing import List, Optional

from core.infrastructure._http import http_get_json

logger = logging.getLogger(__name__)

_LETRAS_URL = "https://api.argentinadatos.com/v1/finanzas/letras"
_TTL_S = 3600  # 1 hora

_RIESGO_PAIS_URL      = "https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais/ultimo"
_RIESGO_PAIS_HIST_URL = "https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais"
_RP_TTL_S      = 300   # 5 min — valor actual
_RP_HIST_TTL_S = 3600  # 1 hora — valor anterior (delta diario)

# --- OVERRIDE TEMPORAL (ambito.com) -----------------------------------------
# La API de ArgentinaDatos dejó de actualizar el riesgo país. Mientras tanto
# tomamos el valor del widget de ambito.com (la misma fuente que muestra
# https://www.ambito.com/contenidos/riesgo-pais.html). La página embebe un
# widget JS que lee este endpoint JSON, así que vamos directo a él:
#   {"ultimo":"428","fecha":"17-06-2026","variacion":"-0,47%", ...}
# El fetch de ArgentinaDatos se mantiene vivo (no se mata el proceso); solo se
# suplanta el valor mostrado. Para revertir: borrar este bloque, el método
# `_fetch_ambito_riesgo_pais`, y el override al final de `get_riesgo_pais`.
_AMBITO_RP_URL = "https://mercados.ambito.com/riesgopais/variacion-ultimo"
_AMBITO_RP_TTL_S = 300  # 5 min

# Cotizaciones de dólares (histórico). Las casas coinciden 1:1 con dolarapi
# (oficial, blue, bolsa, contadoconliqui, mayorista, cripto, tarjeta). Se usa
# como baseline del cierre anterior para la variación diaria del strip FX
# cuando el acumulado local (fx_prices_daily.json) todavía no tiene día previo.
_DOLARES_HIST_URL = "https://api.argentinadatos.com/v1/cotizaciones/dolares"
_DOLARES_TTL_S    = 3600  # 1 hora — el cierre del día anterior cambia 1x/día


class ArgentinaDatosProvider:
    def __init__(self):
        self._cache: Optional[List[dict]] = None
        self._cache_ts: float = 0.0
        self._lock = threading.Lock()
        self._rp_cache: Optional[dict] = None
        self._rp_cache_ts: float = 0.0
        self._rp_lock = threading.Lock()
        self._rp_hist: Optional[List[dict]] = None
        self._rp_hist_ts: float = 0.0
        self._dolares_prev: Optional[dict] = None
        self._dolares_prev_ts: float = 0.0
        self._dolares_lock = threading.Lock()
        self._ambito_rp: Optional[dict] = None  # override temporal ambito.com
        self._ambito_rp_ts: float = 0.0
        self._ambito_rp_lock = threading.Lock()

    def fetch_letras(self, *, force: bool = False) -> List[dict]:
        """Devuelve la lista completa de letras activas. Thread-safe."""
        with self._lock:
            if (
                not force
                and self._cache is not None
                and (time.monotonic() - self._cache_ts) < _TTL_S
            ):
                return self._cache
            try:
                data = http_get_json(
                    _LETRAS_URL,
                    timeout=10,
                    user_agent="balanz-monitor/1.0",
                    source="ArgentinaDatos/letras",
                )
                if not isinstance(data, list):
                    raise ValueError(f"expected list, got {type(data).__name__}")
                self._cache = data
                self._cache_ts = time.monotonic()
                logger.info("ArgentinaDatos: %d letras cargadas.", len(data))
            except Exception as e:
                logger.warning("ArgentinaDatos letras fetch failed: %s", e)
            return self._cache or []

    def get_by_ticker(self, ticker: str) -> Optional[dict]:
        """Busca una letra por ticker (case-insensitive). None si no existe."""
        t = ticker.upper().strip()
        for row in self.fetch_letras():
            if str(row.get("ticker", "")).upper().strip() == t:
                return row
        return None

    def _fetch_hist(self) -> List[dict]:
        """Serie histórica completa, ordenada por fecha ascendente. Cache 1h.

        Solo conserva filas con `valor` y `fecha`. Las fechas son ISO
        (YYYY-MM-DD) → el orden lexicográfico coincide con el cronológico."""
        if (
            self._rp_hist is not None
            and (time.monotonic() - self._rp_hist_ts) < _RP_HIST_TTL_S
        ):
            return self._rp_hist
        try:
            data = http_get_json(
                _RIESGO_PAIS_HIST_URL,
                timeout=15,
                user_agent="balanz-monitor/1.0",
                source="ArgentinaDatos/riesgo-pais-hist",
            )
            if isinstance(data, list) and data:
                self._rp_hist = sorted(
                    (r for r in data if "valor" in r and r.get("fecha")),
                    key=lambda r: str(r["fecha"]),
                )
                self._rp_hist_ts = time.monotonic()
        except Exception as e:
            logger.warning("Riesgo País hist fetch failed: %s", e)
        return self._rp_hist or []

    @staticmethod
    def _is_stale(fecha: str) -> bool:
        """True si `fecha` quedó dos o más días hábiles atrás respecto de hoy.

        El EMBI suele publicarse con hasta un día hábil de rezago, así que se
        tolera que el dato sea de la rueda anterior; recién se marca stale a
        partir de dos ruedas atrás (el síntoma observado: dato del lunes
        mostrándose el miércoles).

        Cuenta días hábiles en (fecha, hoy]. Usa el calendario BYMA si está
        disponible (contempla feriados); si no, cae a un conteo lun-vie —
        sin dependencias ni red — que igual detecta el atraso aunque ignore
        feriados puntuales. Así el flag nunca queda silenciosamente apagado
        por una dependencia faltante."""
        from datetime import date as _date, timedelta
        if not fecha:
            return False
        try:
            y, m, d = (int(x) for x in fecha[:10].split("-"))
            f = _date(y, m, d)
        except Exception:
            return False
        today = _date.today()
        if f >= today:
            return False
        try:
            from core.holiday_engine import date_range_habil
            habiles = date_range_habil((f + timedelta(days=1)).isoformat(), today.isoformat())
            return len(habiles) >= 2
        except Exception:
            bdays, cur = 0, f
            while cur < today:
                cur += timedelta(days=1)
                if cur.weekday() < 5:  # 0=lunes … 4=viernes
                    bdays += 1
            return bdays >= 2

    def _fetch_ambito_riesgo_pais(self) -> Optional[dict]:
        """OVERRIDE TEMPORAL — riesgo país desde el widget de ambito.com.

        Devuelve {valor, fecha, delta_abs, delta_pct, stale} en el mismo formato
        que `get_riesgo_pais`, o None si el fetch/parseo falla. Cache 5 min.

        El endpoint trae strings al estilo widget:
          {"ultimo":"428","fecha":"17-06-2026","variacion":"-0,47%"}
        - `ultimo`: bps como string → int.
        - `fecha`: dd-mm-yyyy → ISO yyyy-mm-dd (para el chequeo de stale).
        - `variacion`: % con coma decimal → delta_pct; delta_abs se deriva del
          valor previo implícito (valor / (1 + pct/100)).
        """
        with self._ambito_rp_lock:
            if (
                self._ambito_rp is not None
                and (time.monotonic() - self._ambito_rp_ts) < _AMBITO_RP_TTL_S
            ):
                return self._ambito_rp
            try:
                data = http_get_json(
                    _AMBITO_RP_URL,
                    timeout=10,
                    user_agent="Mozilla/5.0 (balanz-monitor)",
                    source="ambito/riesgo-pais",
                )
                if not isinstance(data, dict) or "ultimo" not in data:
                    raise ValueError("respuesta inesperada de ambito")
                valor = int(round(float(str(data["ultimo"]).replace(".", "").replace(",", "."))))

                fecha_raw = str(data.get("fecha", "")).strip()
                fecha = fecha_raw
                parts = fecha_raw.split("-")
                if len(parts) == 3 and len(parts[0]) == 2:  # dd-mm-yyyy → ISO
                    d, m, y = parts
                    fecha = f"{y}-{m}-{d}"

                delta_pct = None
                delta_abs = None
                var_raw = str(data.get("variacion", "")).replace("%", "").replace(",", ".").strip()
                if var_raw:
                    try:
                        delta_pct = round(float(var_raw), 1)
                        prev = valor / (1 + delta_pct / 100) if delta_pct != -100 else None
                        if prev:
                            delta_abs = int(round(valor - prev))
                    except ValueError:
                        pass

                self._ambito_rp = {
                    "valor": valor,
                    "fecha": fecha,
                    "delta_abs": delta_abs,
                    "delta_pct": delta_pct,
                    "stale": self._is_stale(fecha),
                }
                self._ambito_rp_ts = time.monotonic()
                logger.info("Riesgo País (ambito override): %s bps (%s)", valor, fecha)
            except Exception as e:
                logger.warning("Riesgo País ambito fetch failed: %s", e)
            return self._ambito_rp

    def get_riesgo_pais(self) -> Optional[dict]:
        """Último valor de riesgo país, lo más fiel posible al día de hoy.

        Devuelve {valor, fecha, delta_abs, delta_pct, stale} o None. `fecha` es
        la del dato realmente mostrado; `stale` indica que ese dato quedó
        atrasado (más de un día hábil) y no refleja la rueda más reciente.

        OVERRIDE TEMPORAL: mientras ArgentinaDatos no actualice, si ambito.com
        responde se devuelve ese valor en lugar del de ArgentinaDatos. El fetch
        de ArgentinaDatos se mantiene (abajo) para no matar el proceso."""
        ambito = self._fetch_ambito_riesgo_pais()
        ardatos = self._get_riesgo_pais_argentinadatos()
        return ambito or ardatos

    def _get_riesgo_pais_argentinadatos(self) -> Optional[dict]:
        """Riesgo país desde ArgentinaDatos. Ver `get_riesgo_pais` para el
        formato del dict devuelto."""
        with self._rp_lock:
            if (
                self._rp_cache is not None
                and (time.monotonic() - self._rp_cache_ts) < _RP_TTL_S
            ):
                return self._rp_cache
            try:
                data = http_get_json(
                    _RIESGO_PAIS_URL,
                    timeout=10,
                    user_agent="balanz-monitor/1.0",
                    source="ArgentinaDatos/riesgo-pais",
                )
                ultimo = data if (isinstance(data, dict) and "valor" in data) else None
                hist = self._fetch_hist()

                # Valor actual = el de mayor fecha entre /ultimo y el histórico.
                # Los dos archivos pueden desincronizarse; tomamos el más fresco
                # para mostrar el dato más fiel del día y avisamos si difieren.
                current = ultimo
                if hist:
                    hlast = hist[-1]
                    cur_fecha = str(current.get("fecha", "")) if current else ""
                    if current is None or str(hlast["fecha"]) > cur_fecha:
                        current = hlast
                    elif str(hlast["fecha"]) != cur_fecha:
                        logger.warning(
                            "Riesgo País: /ultimo (%s) y histórico (%s) desincronizados",
                            cur_fecha, hlast["fecha"],
                        )
                if current is None:
                    # Sin dato nuevo utilizable: conservamos el último bueno.
                    return self._rp_cache

                valor = current["valor"]
                fecha = str(current.get("fecha", ""))

                # Día anterior: última entrada del histórico con fecha < actual.
                prev = next(
                    (r["valor"] for r in reversed(hist) if str(r["fecha"]) < fecha),
                    None,
                )
                delta_abs = (valor - prev) if prev is not None else None
                delta_pct = round(delta_abs / prev * 100, 1) if prev else None
                stale = self._is_stale(fecha)
                self._rp_cache = {
                    "valor": valor,
                    "fecha": fecha,
                    "delta_abs": delta_abs,
                    "delta_pct": delta_pct,
                    "stale": stale,
                }
                self._rp_cache_ts = time.monotonic()
                logger.info(
                    "Riesgo País: %s bps (%s)%s Δ%+d (%+.1f%%)",
                    valor, fecha, " [STALE]" if stale else "",
                    delta_abs if delta_abs is not None else 0,
                    delta_pct if delta_pct is not None else 0,
                )
            except Exception as e:
                logger.warning("Riesgo País fetch failed: %s", e)
            return self._rp_cache

    def get_dolares_prev_close(self) -> dict:
        """Cierre (venta/compra) del último día hábil estrictamente anterior a
        hoy, por casa. Devuelve {casa: {'compra','venta','fecha'}}. Cache 1h.

        Baseline para la variación diaria del strip FX: dolarapi no provee el
        cierre previo, así que se toma de ArgentinaDatos. Las casas coinciden
        con las de dolarapi (oficial, blue, bolsa, contadoconliqui, mayorista,
        cripto, tarjeta)."""
        from datetime import date as _date
        with self._dolares_lock:
            if (
                self._dolares_prev is not None
                and (time.monotonic() - self._dolares_prev_ts) < _DOLARES_TTL_S
            ):
                return self._dolares_prev
            try:
                data = http_get_json(
                    _DOLARES_HIST_URL,
                    timeout=15,
                    user_agent="balanz-monitor/1.0",
                    source="ArgentinaDatos/dolares",
                )
                if isinstance(data, list):
                    today = _date.today().isoformat()
                    prev: dict = {}
                    for row in data:
                        fecha = str(row.get("fecha", ""))
                        casa  = str(row.get("casa", "")).strip().lower()
                        if not casa or not fecha or fecha >= today:
                            continue
                        cur = prev.get(casa)
                        if cur is None or fecha > cur["fecha"]:
                            prev[casa] = {
                                "compra": row.get("compra"),
                                "venta":  row.get("venta"),
                                "fecha":  fecha,
                            }
                    if prev:
                        self._dolares_prev = prev
                        self._dolares_prev_ts = time.monotonic()
            except Exception as e:
                logger.warning("ArgentinaDatos dolares hist fetch failed: %s", e)
            return self._dolares_prev or {}


# Singleton a nivel de módulo — compartido por todos los endpoints.
_provider: Optional[ArgentinaDatosProvider] = None
_provider_lock = threading.Lock()


def get_provider() -> ArgentinaDatosProvider:
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = ArgentinaDatosProvider()
    return _provider
