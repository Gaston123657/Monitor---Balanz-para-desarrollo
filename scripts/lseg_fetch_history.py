"""Baja precios históricos diarios desde LSEG Workspace para el backfill del histórico.

Corre en el venv AISLADO (pandas<3, ver LSEG-WORKSPACE-README.txt):

    .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_history.py --days 120

REQUISITO: LSEG Workspace Desktop ABIERTO y LOGUEADO (Desktop Session,
handshake localhost:9000).

QUÉ HACE
--------
1. Lee el mapa ticker->instrumento LSEG de data/history/lseg_ric_map.json. Formato:
       { "AL30D": {"universe_id": "ARARGT...=BA", "panel": "bonares"}, ... }
   Para los tickers sin entrada (y con `isin_local`), intenta resolver vía
   GovCorpInstruments (misma lógica que scripts/lseg_fetch_ons.py) y cachea el
   resultado de vuelta en el mapa.
2. Baja la serie diaria de precio (y volumen si está) entre start/end (o los
   últimos --days días) con ld.get_history.
3. Vuelca todo a data/history/_lseg_prices_raw.json:
       { "AL30D": {"panel": "bonares", "universe_id": "...",
                   "prices": [{"fecha": "2026-04-01", "close": 63.1, "volume": ...}, ...]} }

El recálculo de TIR/paridad/duration NO se hace acá (LSEG no las da): lo hace
`scripts/backfill_history.py` en el entorno principal, reusando FinancialEngine.

CAVEAT DE PRECIO: el recálculo trata `close` como precio DIRTY en la MISMA moneda
que Data912 (soberanos sufijo D = USD/MEP; pesos para CER/DL/tasa fija). Verificá
con un spot-check que el campo de LSEG elegido coincida con esa convención (clean
vs dirty cambia la paridad por el accrued).
"""
import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import lseg.data as ld
from lseg.data.content import search

RIC_MAP = ROOT / "data" / "history" / "lseg_ric_map.json"
OUT = ROOT / "data" / "history" / "_lseg_prices_raw.json"

def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # filtra NaN
    except (TypeError, ValueError):
        return None


def _search(query, top=10):
    """Wrapper de search en GOV_CORP_INSTRUMENTS -> lista de records con RIC válido."""
    try:
        r = search.Definition(
            view=search.Views.GOV_CORP_INSTRUMENTS,
            query=query,
            select="DocumentTitle,RIC,ISIN,Currency",
            top=top,
        ).get_data()
        df = r.data.df
    except Exception as e:
        return None, f"search_error:{type(e).__name__}"
    if df is None or not len(df) or "RIC" not in df.columns:
        return [], "no_match"
    rows = [x for x in df.to_dict("records") if x.get("RIC") and str(x["RIC"]) != "<NA>"]
    return rows, "ok"


def _resolve_soberano(ticker):
    """SOBERANOS USD (BONAR/GLOBAL, sufijo D): buscar por root, emisor 'Argentina',
    preferir USD. Devuelve RIC (ej. ARAE38=, 040114HS2=). [camino original validado]"""
    root = ticker[:-1] if ticker.upper().endswith("D") else ticker
    rows, note = _search(root)
    if not rows:
        return None, note if isinstance(note, str) else "no_match"
    arg = [x for x in rows if "Argentina" in str(x.get("DocumentTitle", ""))]
    rows = arg or rows
    usd = [x for x in rows if str(x.get("Currency")) == "USD"]
    rows = usd or rows
    return (str(rows[0]["RIC"]), "resolved") if rows else (None, "no_match")


def resolve(ticker, isin_local, panel):
    """ticker local Balanz -> RIC de cotización LSEG (para get_history), por familia.

    Hallazgos fase 2 (ver HISTORICO-BACKFILL-FASE2.txt §RIC descubiertos):
      - bonares    : search por root, emisor Argentina, USD  -> ARxxx= / ISIN= (globales)
      - bopreales  : emisor BCRA. RIC CONSTRUIDO: BPA7D -> ARBPOA7= (insertar 'O' tras
                     'BP', sacar 'D'). MID_PRICE USD per-100, factor 1 (como soberanos).
      - cer/tasa_fija: RIC CONSTRUIDO AR<ticker>= (cotización *evaluated*). MID_PRICE =
                     dirty per-100 en PESOS, factor 1 (validado vs Data912). Los que solo
                     tienen listado de bolsa AR..Z=BA (OHLC, escala basura/stale) NO
                     resuelven acá y quedan sin data (se saltean, se loguea).
      - dolar_linked: search por ticker, preferir AR<ticker>=, quedarse con USD evaluated.
                     MID_PRICE viene en USD -> se convierte a pesos ×FX (ARS=) en fetch.
      - ons_*      : sus RIC (AR<ticker>O= / AR..Z=BA) NO tienen serie diaria en LSEG
                     (get_history vacío). No factible por ahora -> None.
    """
    t = ticker.upper()
    if panel == "bonares":
        return _resolve_soberano(ticker)
    if panel == "bopreales":
        mid = t[2:-1] if t.endswith("D") else t[2:]   # BPA7D -> A7
        return f"ARBPO{mid}=", "bopreal_constructed"
    if panel in ("cer", "tasa_fija"):
        return f"AR{t}=", "ars_constructed"
    if panel == "dolar_linked":
        rows, note = _search(t)
        if not rows:
            return None, note if isinstance(note, str) else "no_match"
        prefer = f"AR{t}="
        exact = [x for x in rows if str(x["RIC"]) == prefer]
        if exact:
            return prefer, "dl_resolved_exact"
        usd = [x for x in rows if str(x.get("Currency")) == "USD"]
        rows = usd or rows
        return str(rows[0]["RIC"]), "dl_resolved_search"
    if panel in ("ons_ny", "ons_ar"):
        return None, "ons_sin_historico_lseg"
    return None, f"panel_desconocido:{panel}"


def _fetch_evaluated(df, panel, fx_by_date):
    """Familias en PESOS/DL sobre cotización *evaluated*: exige MID_PRICE (rechaza
    listados de bolsa OHLC-only cuya escala es basura). Para dolar_linked convierte
    USD->pesos con FX as-of (ARS= MID). `close` queda en la misma moneda que Data912:
    pesos per-100 dirty (CER/tasa fija = MID_PRICE directo; DL = MID_PRICE × FX)."""
    cols = list(df.columns)
    if "MID_PRICE" not in cols:
        print(f"    sin MID_PRICE (evaluated) — cols={cols[:8]} — salteado")
        return []
    out = []
    for idx, row in df.iterrows():
        fecha = str(idx)[:10]
        mid = _num(row.get("MID_PRICE"))
        if mid is None or mid <= 0:
            continue
        if panel == "dolar_linked":
            fx = (fx_by_date or {}).get(fecha)
            if fx is None or fx <= 0:
                continue  # sin FX as-of esa fecha -> no se puede pasar a pesos
            close = mid * fx
            out.append({"fecha": fecha, "close": close, "clean": mid, "fx": fx})
        else:
            out.append({"fecha": fecha, "close": mid, "clean": mid})
    return out


def fetch_series(ric, start, end, panel="bonares", fx_by_date=None):
    """[{fecha, close, clean, ...}] o []. `close` es el precio DIRTY en la MISMA
    moneda/escala que Data912 (soberanos/bopreales = USD per-100; CER/tasa fija = pesos
    per-100; DL = pesos per-100 vía ×FX). El recálculo de TIR/paridad lo hace
    backfill_history reusando FinancialEngine."""
    try:
        df = ld.get_history(universe=ric, interval="daily", start=start, end=end)
    except Exception as e:
        print(f"    get_history error {type(e).__name__}: {e}")
        return []
    if df is None or not len(df):
        return []
    # Familias en pesos / dólar-linked: cotización evaluated, solo MID_PRICE.
    if panel in ("cer", "tasa_fija", "dolar_linked"):
        return _fetch_evaluated(df, panel, fx_by_date)

    # Soberanos + bopreales (hard-dollar USD): DIRTY_PRC si está; si no MID_PRICE
    # (clean) + ACCR_INT. Bopreales no traen DIRTY_PRC ni ACCR_INT -> MID_PRICE.
    cols = list(df.columns)
    has_dirty = "DIRTY_PRC" in cols
    price_col = next((c for c in ["MID_PRICE", "TRTN_PRICE", "BID"] if c in cols), None)
    if not has_dirty and price_col is None:
        print(f"    sin columna de precio (cols={cols[:8]})")
        return []
    vol_col = next((c for c in ["ACVOL_UNS", "NUM_MOVES"] if c in cols), None)
    out = []
    for idx, row in df.iterrows():
        fecha = str(idx)[:10]
        accrued = _num(row.get("ACCR_INT")) if "ACCR_INT" in cols else None
        if has_dirty and _num(row.get("DIRTY_PRC")) is not None:
            clean = _num(row.get(price_col)) if price_col else None
            dirty = _num(row.get("DIRTY_PRC"))
        else:
            clean = _num(row.get(price_col))
            if clean is None:
                continue
            dirty = clean + (accrued or 0.0)
        rec = {"fecha": fecha, "close": dirty, "clean": clean, "accrued": accrued}
        if vol_col is not None:
            rec["volume"] = _num(row.get(vol_col))
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120, help="días hacia atrás desde hoy")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD (sobreescribe --days)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (default hoy)")
    ap.add_argument("--panels", default="bonares",
                    help="paneles a procesar, coma-separados (default: bonares). "
                         "La resolución de RIC está validada para soberanos USD; "
                         "las familias en pesos quedan para una 2da fase.")
    args = ap.parse_args()
    panels = {p.strip() for p in args.panels.split(",") if p.strip()}

    end = args.end or date.today().isoformat()
    start = args.start or (date.today() - timedelta(days=args.days)).isoformat()

    if not RIC_MAP.is_file():
        raise SystemExit(f"Falta {RIC_MAP}. Creá el mapa ticker->universe_id (ver docstring).")
    full_map = json.loads(RIC_MAP.read_text(encoding="utf-8"))
    # Filtramos por panel para procesar, pero conservamos full_map para el writeback
    # (los `info` son las MISMAS refs, así que actualizarlos persiste en full_map).
    ric_map = {tk: info for tk, info in full_map.items() if info.get("panel") in panels}

    sess = ld.session.desktop.Definition(app_key=os.environ["LSEG_APP_KEY"]).get_session()
    ld.session.set_default(sess)
    sess.open()
    print(f"LSEG session OPEN · rango {start}..{end} · paneles={sorted(panels)} · {len(ric_map)} tickers")

    # FX as-of para dólar-linked: serie USD/ARS (ARS= MID) -> {fecha: fx}. DL viene en
    # USD en LSEG y Data912 lo da en pesos, así que pasamos a pesos = MID_PRICE × FX.
    fx_by_date = {}
    if "dolar_linked" in panels:
        try:
            dfx = ld.get_history(universe="ARS=", interval="daily", start=start, end=end)
            if dfx is not None and "MID_PRICE" in dfx.columns:
                for idx, row in dfx.iterrows():
                    v = _num(row.get("MID_PRICE"))
                    if v:
                        fx_by_date[str(idx)[:10]] = v
            print(f"FX ARS= cargado: {len(fx_by_date)} fechas")
        except Exception as e:
            print(f"FX ARS= error {type(e).__name__}: {e} — dólar-linked quedará sin convertir")

    result = {}
    map_dirty = False
    for i, (ticker, info) in enumerate(sorted(ric_map.items()), 1):
        panel = info.get("panel")
        uid = info.get("universe_id")
        note = "cached"
        if not uid:
            uid, note = resolve(ticker, info.get("isin_local"), panel)
        if not uid:
            print(f"[{i}/{len(ric_map)}] {ticker} ({panel}): NO RESUELTO ({note})")
            continue
        series = fetch_series(uid, start, end, panel, fx_by_date)
        print(f"[{i}/{len(ric_map)}] {ticker} ({panel}): {uid} [{note}] -> {len(series)} barras")
        if series:
            # Cachear el RIC solo si trajo data (no persistir RICs muertos).
            if info.get("universe_id") != uid:
                info["universe_id"] = uid
                map_dirty = True
            result[ticker] = {
                "panel": panel,
                "universe_id": uid,
                "prices": series,
            }

    if map_dirty:
        RIC_MAP.write_text(json.dumps(full_map, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Mapa actualizado: {RIC_MAP}")
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Guardado {OUT} · {len(result)} tickers con data")
    sess.close()


if __name__ == "__main__":
    main()
