"""Store histórico de mercado — snapshots diarios long/tidy particionados por mes.

Una fila por (fecha, ticker) con todas las métricas que muestra el monitor. Persiste
en CSV mensual (`data/history/snapshots/YYYY-MM.csv`) para no agregar dependencias
(pandas==3.0.3 ya está, pero `pyarrow` para Parquet no está instalado). Mismo schema
para captura *live* y backfill LSEG, así la UI no distingue el origen.

Diseño:
- `append_snapshot` mergea/upsertea un día entero en la partición de su mes, dedupea
  por (fecha, ticker) quedándose con la última escritura (cierre), y guarda atómico
  (`.tmp` + `os.replace`, igual que instruments_abm) para no corromper en crash.
- Lecturas cachean por mtime de la partición (patrón de `_serve_bei_history`).
- Lock de módulo (RLock) para thread-safety entre el refresh loop y los handlers HTTP.
"""

import logging
import os
import threading
from typing import Dict, List, Optional

import pandas as pd

from config.settings import HISTORY_SNAPSHOTS_DIR

logger = logging.getLogger(__name__)

# Schema canónico — orden de columnas del CSV. Reusa las claves de _base_bond_row.
COLUMNS: List[str] = [
    "fecha", "ticker", "panel",
    "price", "technical_value", "parity", "tir",
    "tna", "tem", "tna_360", "tem_360",
    "duration", "change_pct", "volume", "source",
]

# Métricas válidas para read_series (serie temporal por instrumento).
METRICS = frozenset({
    "price", "technical_value", "parity", "tir",
    "tna", "tem", "tna_360", "tem_360", "duration", "change_pct", "volume",
})

_LOCK = threading.RLock()

# Cache de DataFrames por partición, invalidado por mtime.
_cache: Dict[str, tuple] = {}  # month -> (mtime, DataFrame)


def _month_of(fecha: str) -> str:
    """'2026-06-19' -> '2026-06'. Asume fecha ISO YYYY-MM-DD."""
    return fecha[:7]


def _path_for_month(month: str) -> str:
    return os.path.join(HISTORY_SNAPSHOTS_DIR, f"{month}.csv")


def _read_month(month: str) -> Optional[pd.DataFrame]:
    """DataFrame de una partición mensual, o None si no existe. Cacheado por mtime."""
    path = _path_for_month(month)
    if not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    cached = _cache.get(month)
    if cached and cached[0] == mtime:
        return cached[1]
    df = pd.read_csv(path, dtype={"fecha": str, "ticker": str, "panel": str, "source": str})
    _cache[month] = (mtime, df)
    return df


def append_snapshot(fecha: str, rows: List[dict], source: str = "live") -> int:
    """Upsert idempotente del snapshot de un día en la partición de su mes.

    `rows` son dicts con claves de `_base_bond_row` (deben incluir 'ticker' y 'panel').
    Reescribe la fila de cada (fecha, ticker) si ya existía (la última escritura gana,
    = cierre del día). Devuelve la cantidad de filas escritas para ese día.
    """
    if not rows:
        return 0

    norm = []
    for r in rows:
        ticker = r.get("ticker")
        if not ticker:
            continue
        rec = {c: r.get(c) for c in COLUMNS}
        rec["fecha"] = fecha
        rec["ticker"] = ticker
        rec["source"] = source
        norm.append(rec)
    if not norm:
        return 0

    new_df = pd.DataFrame(norm, columns=COLUMNS)
    month = _month_of(fecha)
    path = _path_for_month(month)

    with _LOCK:
        os.makedirs(HISTORY_SNAPSHOTS_DIR, exist_ok=True)
        existing = _read_month(month)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
        # Upsert por (fecha, ticker): la última escritura gana. No borra el día
        # entero, así backfill (LSEG) y captura live conviven sin pisarse tickers.
        combined = combined.drop_duplicates(subset=["fecha", "ticker"], keep="last")
        combined = combined.sort_values(["fecha", "ticker"]).reset_index(drop=True)

        tmp = path + ".tmp"
        combined.to_csv(tmp, index=False)
        os.replace(tmp, path)
        # Invalida cache (mtime cambió; el próximo _read_month relee).
        _cache.pop(month, None)

    logger.info("history_store: %d filas escritas para %s (%s)", len(norm), fecha, source)
    return len(norm)


def _all_month_files() -> List[str]:
    if not os.path.isdir(HISTORY_SNAPSHOTS_DIR):
        return []
    return sorted(
        f[:-4] for f in os.listdir(HISTORY_SNAPSHOTS_DIR)
        if f.endswith(".csv") and not f.endswith(".tmp")
    )


def read_curve(panel: str, fechas: List[str]) -> Dict[str, List[dict]]:
    """Para cada fecha pedida, la lista de puntos {ticker, md, tir} del panel.

    `md` = duration (eje X de la curva), `tir` = TIR (eje Y). Filtra filas sin
    duration o TIR (no se pueden ubicar en la curva).
    """
    out: Dict[str, List[dict]] = {f: [] for f in fechas}
    with _LOCK:
        # Agrupar fechas por mes para leer cada partición una sola vez.
        by_month: Dict[str, List[str]] = {}
        for f in fechas:
            by_month.setdefault(_month_of(f), []).append(f)

        for month, month_fechas in by_month.items():
            df = _read_month(month)
            if df is None or df.empty:
                continue
            sub = df[(df["panel"] == panel) & (df["fecha"].isin(month_fechas))]
            for fecha in month_fechas:
                rows = sub[sub["fecha"] == fecha]
                pts = []
                for _, r in rows.iterrows():
                    md = r.get("duration")
                    tir = r.get("tir")
                    if pd.isna(md) or pd.isna(tir):
                        continue
                    pts.append({
                        "ticker": r["ticker"],
                        "md": float(md),
                        "tir": float(tir),
                    })
                pts.sort(key=lambda p: p["md"])
                out[fecha] = pts
    return out


def read_series(ticker: str, metric: str) -> List[dict]:
    """Serie temporal [{fecha, valor}] de una métrica para un ticker, en todas las
    particiones. Ordenada por fecha ascendente."""
    if metric not in METRICS:
        raise ValueError(f"métrica inválida: {metric!r}. Válidas: {sorted(METRICS)}")
    serie: List[dict] = []
    with _LOCK:
        for month in _all_month_files():
            df = _read_month(month)
            if df is None or df.empty:
                continue
            sub = df[df["ticker"] == ticker]
            for _, r in sub.iterrows():
                val = r.get(metric)
                if pd.isna(val):
                    continue
                serie.append({"fecha": r["fecha"], "valor": float(val)})
    serie.sort(key=lambda x: x["fecha"])
    return serie


def available_dates(panel: Optional[str] = None) -> List[str]:
    """Fechas con data (opcionalmente filtradas por panel), ascendente."""
    fechas = set()
    with _LOCK:
        for month in _all_month_files():
            df = _read_month(month)
            if df is None or df.empty:
                continue
            if panel:
                df = df[df["panel"] == panel]
            fechas.update(df["fecha"].unique().tolist())
    return sorted(fechas)


def available_tickers(panel: Optional[str] = None) -> List[str]:
    """Tickers con data (opcionalmente filtrados por panel), alfabético."""
    tickers = set()
    with _LOCK:
        for month in _all_month_files():
            df = _read_month(month)
            if df is None or df.empty:
                continue
            if panel:
                df = df[df["panel"] == panel]
            tickers.update(df["ticker"].unique().tolist())
    return sorted(tickers)
