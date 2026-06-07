"""CAFCI mutual-fund (FCI) data with on-disk persistence.

Architectural exception: market prices come from Data912, but Argentine mutual
fund (FCI) returns are published only by CAFCI (Cámara Argentina de Fondos
Comunes de Inversión).

The historical `fedemoglia/cafci-api` approach (hit `api.cafci.org.ar` with no
auth) is dead: that host now sits behind a CloudFront route allowlist that
answers ``{"error":"Route not allowed"}`` (403) to every path. The live public
source is the *estadísticas* micrositio, whose comparador endpoint bundles —
in a single daily-refreshed JSON — both the full fund catalog and the daily
returns matrix for every priced class:

    https://estadisticas.cafci.org.ar/comparador-de-fondos.json
      catalogo : { fondos: [ {id, nombre, tipo_renta, moneda, sociedad_gerente,
                              dias_liquidacion, valuacion, clases:[{id, nombre,
                              moneda, ...}] } ] }      (~1149 fondos / 4602 clases)
      matriz   : { fecha_base, generated_at,
                   clases: { "<clase_id>": { valor_cuotaparte, fecha_valor,
                              dias_7:{tna,directo}, mes_1:{...}, dias_90, dias_180,
                              ytd, meses_12 } } }       (~3723 clases con precio)

We join `catalogo` (metadata) with `matriz` (daily returns) on `clase_id`.

Resilience (mirrors `BCRAIndicesProvider`): the parsed dataset is mirrored to
``data/history/cafci_diario.json``. On startup the cache hydrates from disk;
CAFCI is queried at most once per successful day (with a short retry cooldown
on failure). If CAFCI is unreachable the project keeps serving the last
persisted snapshot — only data freshness degrades.
"""

import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional

from config.settings import DATA_DIR
from core.infrastructure._http import http_get_json, http_get_text

logger = logging.getLogger(__name__)


_CAFCI_URL  = "https://estadisticas.cafci.org.ar/comparador-de-fondos.json"
_CAFCI_JSON = os.path.join(DATA_DIR, "history", "cafci_diario.json")

# Composición de cartera — embebida en el HTML del detalle por fondo
# (https://estadisticas.cafci.org.ar/fondos/<fondo_id>?clase=<clase_id>) dentro
# de un atributo `data-pie-chart-items-value` del <canvas> del pie chart.
# CAFCI publica esta composición mensualmente y con ~1 mes de rezago, así que
# el TTL es diario (a demanda) y persistimos por clase en disco.
_CAFCI_COMP_URL = "https://estadisticas.cafci.org.ar/fondos/{fondo_id}?clase={clase_id}"
_CAFCI_COMP_DIR = os.path.join(DATA_DIR, "history", "cafci_composicion")
_RE_PIE_ITEMS = re.compile(r'data-pie-chart-items-value="([^"]+)"')
_RE_COMP_FECHA = re.compile(r'class="valores"[^>]*>\s*Valores al\s*([0-9]{2}/[0-9]{2}/[0-9]{4})')

# Periods present in matriz.clases[*] (no 1-day point upstream — shortest is 7d).
_PERIODS = ("dias_7", "mes_1", "dias_90", "dias_180", "ytd", "meses_12")

# Cooldown between failed fetch attempts so spamming filters while CAFCI is down
# doesn't hammer the upstream (success gates for the rest of the day instead).
_RETRY_COOLDOWN_S = 60.0

# ArgentinaDatos FCI — fallback cuando estadisticas.cafci.org.ar está caído
# y no hay snapshot en disco. Schema: [{fondo, tipo, fecha, vcp, ccp, patrimonio, horizonte}]
# Cubre las 5 categorías estándar (exluye 'otros' y 'variables' que tienen schema distinto).
_ARD_FCI_CATEGORIAS = {
    "Mercado de Dinero": "https://argentinadatos.com/v1/finanzas/fci/mercadoDinero/ultimo",
    "Renta Variable":    "https://argentinadatos.com/v1/finanzas/fci/rentaVariable/ultimo",
    "Renta Fija":        "https://argentinadatos.com/v1/finanzas/fci/rentaFija/ultimo",
    "Renta Mixta":       "https://argentinadatos.com/v1/finanzas/fci/rentaMixta/ultimo",
    "Retorno Total":     "https://argentinadatos.com/v1/finanzas/fci/retornoTotal/ultimo",
}


def _to_float(v: Any) -> Optional[float]:
    """CAFCI returns numbers as strings ("230993.537"). Parse leniently."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(s: Any) -> str:
    """Lowercase + strip accents for accent-insensitive name search."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _parse_payload(payload: dict) -> dict:
    """Join catalogo (metadata) + matriz (daily returns) into a flat record list.

    Only classes present in `matriz` (i.e. with a current valuation) are kept —
    closed/unpriced classes have catalog metadata but no returns.
    """
    catalogo = payload.get("catalogo") or {}
    matriz = payload.get("matriz") or {}
    fondos = catalogo.get("fondos") or []
    rend_by_clase = matriz.get("clases") or {}

    funds: List[dict] = []
    for f in fondos:
        tipo_renta = (f.get("tipo_renta") or {}).get("nombre")
        soc = (f.get("sociedad_gerente") or {}).get("nombre")
        fondo_moneda = f.get("moneda") or {}
        for cl in (f.get("clases") or []):
            cid = str(cl.get("id"))
            rend = rend_by_clase.get(cid)
            if not rend:
                continue
            moneda = (cl.get("moneda") or fondo_moneda or {}).get("nombre")
            funds.append({
                "fondo_id": f.get("id"),
                "clase_id": cl.get("id"),
                "fondo_nombre": f.get("nombre"),
                "clase_nombre": cl.get("nombre"),
                "tipo_renta": tipo_renta,
                "moneda": moneda,
                "sociedad": soc,
                "tipo_dinero": f.get("tipo_dinero"),
                "dias_liquidacion": f.get("dias_liquidacion"),
                "valuacion": f.get("valuacion"),
                "vcp": _to_float(rend.get("valor_cuotaparte")),
                "fecha_valor": rend.get("fecha_valor"),
                "rend": {
                    p: {
                        "tna": _to_float((rend.get(p) or {}).get("tna")),
                        "directo": _to_float((rend.get(p) or {}).get("directo")),
                    }
                    for p in _PERIODS
                },
            })

    meta = {
        "fecha_base": matriz.get("fecha_base"),
        "generated_at": matriz.get("generated_at"),
        "total": len(funds),
        "periodos": list(_PERIODS),
    }
    return {"meta": meta, "funds": funds}


def _save_json(path: str, data: dict) -> None:
    """Persist the parsed dataset atomically (.tmp + os.replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"Could not persist {path}: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass


def _load_json(path: str) -> Optional[dict]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("funds"), list):
            return data
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read {path}: {e}")
    return None


class CAFCIProvider:
    """FCI catalog + daily returns from CAFCI, hydrated from disk on startup."""

    _lock = threading.Lock()
    _dataset: dict = {"meta": {}, "funds": []}
    _last_attempt: Optional[date] = None     # date of last *successful* load
    _last_fail_ts: float = 0.0               # monotonic ts of last failed fetch
    _disk_loaded: bool = False
    # Composiciones por clase — cache en memoria { clase_id: {fetched_on, data} }
    # y mirror en disco bajo cafci_composicion/<fondo_id>_<clase_id>.json.
    _composicion: Dict[int, dict] = {}
    _comp_fail_ts: Dict[int, float] = {}
    # Índice paralelo por fondo_id: la composición de cartera es la misma para
    # todas las clases del mismo fondo. Warmeamos 1085 fondos y servimos 3705
    # clases al instante.
    _composicion_by_fondo: Dict[int, dict] = {}
    _warm_started_on: Optional[date] = None

    @classmethod
    def _hydrate_from_disk(cls) -> None:
        data = _load_json(_CAFCI_JSON)
        if data:
            cls._dataset = data
            logger.info(
                "Loaded CAFCI from disk: %d fund classes (fecha_base=%s).",
                len(data.get("funds", [])), (data.get("meta") or {}).get("fecha_base"),
            )
        cls._disk_loaded = True

    @classmethod
    def _fetch_ard_fallback(cls) -> List[dict]:
        """Fallback desde ArgentinaDatos FCI cuando CAFCI y el disco fallan.

        Fetchea las 5 categorías estándar en paralelo. Devuelve fondos con vcp
        pero sin rendimientos por período (rend = None) — degradado pero funcional.
        Solo se activa si el dataset está vacío (no hay snapshot en disco).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        funds: List[dict] = []

        def _fetch_cat(item):
            tipo_renta, url = item
            try:
                rows = http_get_json(
                    url, timeout=10, user_agent="balanz-monitor/1.0",
                    source=f"ARD/FCI/{tipo_renta}",
                )
                if not isinstance(rows, list):
                    return []
                result = []
                for row in rows:
                    nombre = row.get("fondo") or ""
                    if not nombre:
                        continue
                    result.append({
                        "fondo_id":        None,
                        "clase_id":        None,
                        "fondo_nombre":    nombre,
                        "clase_nombre":    None,
                        "tipo_renta":      tipo_renta,
                        "moneda":          "ARS",
                        "sociedad":        None,
                        "tipo_dinero":     None,
                        "dias_liquidacion": None,
                        "valuacion":       None,
                        "vcp":             _to_float(row.get("vcp")),
                        "fecha_valor":     row.get("fecha"),
                        "rend": {p: {"tna": None, "directo": None} for p in _PERIODS},
                    })
                return result
            except Exception as e:
                logger.warning("ARD FCI/%s fallback failed: %s", tipo_renta, e)
                return []

        with ThreadPoolExecutor(max_workers=5) as ex:
            for partial in ex.map(_fetch_cat, list(_ARD_FCI_CATEGORIAS.items())):
                funds.extend(partial)

        return funds

    def _ensure_loaded(self) -> None:
        with self._lock:
            if not self._disk_loaded:
                self._hydrate_from_disk()
            if self._last_attempt == date.today():
                return
            now = time.monotonic()
            if self._last_fail_ts and (now - self._last_fail_ts) < _RETRY_COOLDOWN_S:
                # En cooldown: si no hay datos en disco, intentar ARD como último recurso.
                if not type(self)._dataset.get("funds"):
                    self._apply_ard_fallback()
                return
            try:
                payload = http_get_json(
                    _CAFCI_URL, timeout=30, user_agent="Mozilla/5.0",
                    source="CAFCI/comparador",
                )
                parsed = _parse_payload(payload)
            except Exception as e:
                type(self)._last_fail_ts = now
                logger.warning(f"CAFCI fetch failed: {e}")
                # Sin disco: ARD como fallback inmediato.
                if not type(self)._dataset.get("funds"):
                    self._apply_ard_fallback()
                return
            if parsed["funds"]:
                type(self)._dataset = parsed
                type(self)._last_attempt = date.today()
                _save_json(_CAFCI_JSON, parsed)
                logger.info(
                    "CAFCI: %d fund classes loaded (fecha_base=%s).",
                    len(parsed["funds"]), parsed["meta"].get("fecha_base"),
                )
            else:
                type(self)._last_fail_ts = now
                logger.warning("CAFCI: payload parsed to 0 classes — keeping prior snapshot.")

    def _apply_ard_fallback(self) -> None:
        """Llama al fallback ARD y actualiza el dataset en memoria (sin persistir a disco)."""
        ard_funds = self._fetch_ard_fallback()
        if ard_funds:
            type(self)._dataset = {
                "meta": {
                    "fecha_base": None, "generated_at": None,
                    "total": len(ard_funds), "periodos": list(_PERIODS),
                    "source": "argentinadatos_fallback",
                },
                "funds": ard_funds,
            }
            logger.info(
                "FCI: sirviendo %d fondos desde ArgentinaDatos (fallback, sin rendimientos).",
                len(ard_funds),
            )

    # ------------------------------------------------------------------ #
    # Public accessors
    # ------------------------------------------------------------------ #

    def get_meta(self) -> dict:
        """Snapshot meta + filter option lists (with counts) for the UI."""
        self._ensure_loaded()
        funds = self._dataset.get("funds", [])
        meta = dict(self._dataset.get("meta", {}))

        def _options(key: str) -> List[dict]:
            counts: Dict[str, int] = {}
            for f in funds:
                v = f.get(key)
                if v:
                    counts[v] = counts.get(v, 0) + 1
            return [{"value": k, "count": counts[k]} for k in sorted(counts)]

        meta["tipo_renta_options"] = _options("tipo_renta")
        meta["moneda_options"] = _options("moneda")
        return meta

    def list_funds(
        self,
        tipo_renta: Optional[str] = None,
        moneda: Optional[str] = None,
        query: Optional[str] = None,
        sort: str = "mes_1",
        direction: str = "desc",
        metric: str = "tna",
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Filtered + sorted fund list. Sort is by `metric` (tna|directo) of the
        `sort` period; funds missing that value sink to the bottom regardless of
        direction."""
        self._ensure_loaded()
        funds = self._dataset.get("funds", [])

        if sort not in _PERIODS:
            sort = "mes_1"
        if metric not in ("tna", "directo"):
            metric = "tna"

        q = _norm(query) if query else None
        out = []
        for f in funds:
            if tipo_renta and f.get("tipo_renta") != tipo_renta:
                continue
            if moneda and f.get("moneda") != moneda:
                continue
            if q and q not in _norm(f.get("fondo_nombre")) \
                    and q not in _norm(f.get("clase_nombre")) \
                    and q not in _norm(f.get("sociedad")):
                continue
            out.append(f)

        reverse = direction != "asc"

        def _key(f):
            v = (f.get("rend", {}).get(sort) or {}).get(metric)
            # Missing values always last: pair a presence flag with the value so
            # ordering stays correct for both asc and desc.
            if v is None:
                return (1, 0.0)
            return (0, -v if reverse else v)

        out.sort(key=_key)
        if limit and limit > 0:
            out = out[:limit]
        return out

    def get_fund(self, clase_id) -> Optional[dict]:
        self._ensure_loaded()
        try:
            cid = int(clase_id)
        except (TypeError, ValueError):
            return None
        for f in self._dataset.get("funds", []):
            if f.get("clase_id") == cid:
                return f
        return None

    # ------------------------------------------------------------------ #
    # Composición de cartera (lazy, per‑clase)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _comp_disk_path(fondo_id: int, clase_id: int) -> str:
        return os.path.join(_CAFCI_COMP_DIR, f"{fondo_id}_{clase_id}.json")

    @classmethod
    def _load_comp_from_disk(cls, fondo_id: int, clase_id: int) -> Optional[dict]:
        path = cls._comp_disk_path(fondo_id, clase_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except (OSError, ValueError) as e:
            logger.warning("Could not read %s: %s", path, e)
        return None

    @staticmethod
    def _parse_composicion_html(text: str) -> Optional[dict]:
        m = _RE_PIE_ITEMS.search(text)
        if not m:
            return None
        try:
            raw = html.unescape(m.group(1))
            items_raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
        items: List[dict] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            nombre = it.get("nombre")
            pct = _to_float(it.get("porcentaje"))
            if not nombre or pct is None:
                continue
            items.append({"nombre": str(nombre), "porcentaje": pct})
        if not items:
            return None
        fecha_m = _RE_COMP_FECHA.search(text)
        return {"fecha": fecha_m.group(1) if fecha_m else None, "items": items}

    def get_composicion(self, clase_id) -> Optional[dict]:
        """Composición de cartera (top‑9 + Resto) para una clase de FCI.

        Devuelve `{"fondo_id", "clase_id", "fecha", "items", "fetched_at",
        "stale": bool}` o `None` si la clase no existe en el catálogo. Lanza si
        CAFCI falla y no hay snapshot previo en disco.
        """
        fund = self.get_fund(clase_id)
        if fund is None:
            return None
        try:
            cid = int(clase_id)
        except (TypeError, ValueError):
            return None
        fondo_id = fund.get("fondo_id")
        if not fondo_id:
            return None

        today = date.today()
        fid = int(fondo_id)
        with self._lock:
            cached = type(self)._composicion.get(cid)
            if cached and cached.get("fetched_on") == today:
                return cached["data"]
            # Hit cruzado: otra clase del mismo fondo ya fue fetcheada hoy
            # (composición de cartera == misma para todas las clases).
            fondo_cached = type(self)._composicion_by_fondo.get(fid)
            if fondo_cached and fondo_cached.get("fetched_on") == today:
                data = dict(fondo_cached["data"])
                data["clase_id"] = cid
                type(self)._composicion[cid] = {"fetched_on": today, "data": data}
                return data
            if cached is None:
                disk = self._load_comp_from_disk(fid, cid)
                if disk:
                    cached = {"fetched_on": None, "data": disk}
                    type(self)._composicion[cid] = cached
            now = time.monotonic()
            last_fail = type(self)._comp_fail_ts.get(cid, 0.0)
            in_cooldown = last_fail and (now - last_fail) < _RETRY_COOLDOWN_S

        if in_cooldown:
            if cached:
                stale = dict(cached["data"])
                stale["stale"] = True
                return stale
            raise RuntimeError("CAFCI composicion unavailable (cooldown)")

        url = _CAFCI_COMP_URL.format(fondo_id=fondo_id, clase_id=cid)
        try:
            text = http_get_text(
                url, timeout=15, user_agent="Mozilla/5.0",
                source=f"CAFCI/composicion/{cid}",
            )
        except Exception as e:
            with self._lock:
                type(self)._comp_fail_ts[cid] = time.monotonic()
            logger.warning("CAFCI composicion %s failed: %s", cid, e)
            if cached:
                stale = dict(cached["data"])
                stale["stale"] = True
                return stale
            raise

        parsed = self._parse_composicion_html(text)
        if not parsed:
            with self._lock:
                type(self)._comp_fail_ts[cid] = time.monotonic()
            if cached:
                stale = dict(cached["data"])
                stale["stale"] = True
                return stale
            raise RuntimeError("CAFCI composicion: could not parse pie data")

        data = {
            "fondo_id": int(fondo_id),
            "clase_id": cid,
            "fecha": parsed["fecha"],
            "items": parsed["items"],
            "fetched_at": today.isoformat(),
            "stale": False,
        }
        try:
            os.makedirs(_CAFCI_COMP_DIR, exist_ok=True)
            _save_json(self._comp_disk_path(int(fondo_id), cid), data)
        except OSError as e:
            logger.warning("Could not persist composicion for %s: %s", cid, e)
        with self._lock:
            type(self)._composicion[cid] = {"fetched_on": today, "data": data}
            type(self)._composicion_by_fondo[fid] = {"fetched_on": today, "data": data}
            type(self)._comp_fail_ts.pop(cid, None)
        return data

    # ------------------------------------------------------------------ #
    # Pre-warming en background (1× por día)
    # ------------------------------------------------------------------ #

    def warm_composiciones(self, throttle_s: float = 0.7, workers: int = 2) -> None:
        """Pre-fetch composiciones de cartera para todos los fondos del catálogo.

        Itera fondos únicos por `fondo_id` (no por clase), porque la composición
        es la misma para todas las clases de un fondo. Skip si ya hay disco con
        `fetched_at == hoy`. Throttle suave entre requests y circuit-breaker
        contra fallos sostenidos (CAFCI caído → aborta).

        Idempotente: si ya corrió hoy, no hace nada. Si arrancó pero falló,
        próximas invocaciones del mismo día reintentan los que falten.
        """
        from concurrent.futures import ThreadPoolExecutor

        self._ensure_loaded()
        today = date.today()

        with self._lock:
            if type(self)._warm_started_on == today and \
               len(type(self)._composicion_by_fondo) >= self._unique_fondos_count():
                logger.info("CAFCI warm-up: ya completo para %s, skip.", today)
                return
            type(self)._warm_started_on = today

        # Un (fondo_id, clase_id) representativo por fondo. Filtra fondos sin id.
        seen_fondos: set = set()
        targets: List[tuple] = []
        for f in self._dataset.get("funds", []):
            fid_raw = f.get("fondo_id")
            cid_raw = f.get("clase_id")
            if not fid_raw or not cid_raw:
                continue
            try:
                fid = int(fid_raw)
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            if fid in seen_fondos:
                continue
            seen_fondos.add(fid)
            # Si disco tiene fetched_at == hoy, marcarlo en memoria y skip
            # del fetch — pero hay que cargarlo igual al by_fondo para que
            # las clases hermanas se beneficien.
            disk = self._load_comp_from_disk(fid, cid)
            if disk and disk.get("fetched_at") == today.isoformat():
                with self._lock:
                    type(self)._composicion_by_fondo[fid] = {
                        "fetched_on": today, "data": disk,
                    }
                continue
            targets.append((fid, cid))

        total = len(targets)
        if not total:
            logger.info("CAFCI warm-up: nada que hacer (todo fresh en disco).")
            return

        logger.info(
            "CAFCI warm-up: arrancando para %d fondos (throttle=%.2fs, workers=%d).",
            total, throttle_s, workers,
        )

        success = 0
        fail = 0
        consec_fail = 0
        consec_fail_lock = threading.Lock()
        aborted = threading.Event()
        progress_lock = threading.Lock()
        progress_count = 0

        def _one(target):
            nonlocal success, fail, consec_fail, progress_count
            if aborted.is_set():
                return
            fid, cid = target
            try:
                self.get_composicion(cid)
                with consec_fail_lock:
                    consec_fail = 0
                with progress_lock:
                    success += 1
                    progress_count += 1
                    n = progress_count
                if n % 100 == 0:
                    logger.info("CAFCI warm-up: progreso %d/%d.", n, total)
            except Exception as e:
                with consec_fail_lock:
                    consec_fail += 1
                    cf = consec_fail
                with progress_lock:
                    fail += 1
                    progress_count += 1
                logger.debug("CAFCI warm-up: fondo %s falló: %s", fid, e)
                if cf >= 5:
                    logger.warning(
                        "CAFCI warm-up: %d fallos consecutivos, abortando.", cf,
                    )
                    aborted.set()
            time.sleep(throttle_s)

        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for _ in ex.map(_one, targets):
                    pass
        except RuntimeError as e:
            # Ej. "cannot schedule new futures after interpreter shutdown" —
            # daemon thread atrapado en el shutdown del proceso. Salida limpia.
            logger.info("CAFCI warm-up: interrumpido (%s).", e)
            return

        logger.info(
            "CAFCI warm-up: terminado. success=%d fail=%d total=%d%s",
            success, fail, total, " (abortado)" if aborted.is_set() else "",
        )

    def _unique_fondos_count(self) -> int:
        seen = set()
        for f in self._dataset.get("funds", []):
            fid = f.get("fondo_id")
            if fid:
                seen.add(fid)
        return len(seen)
