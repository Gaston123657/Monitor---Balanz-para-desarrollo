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


def resolve(ticker, isin_local):
    """ticker local Balanz -> RIC de cotización LSEG (para get_history).

    Camino validado para SOBERANOS USD (BONAR/GLOBAL, sufijo D): buscar por el
    root (ticker sin la D) en GovCorpInstruments con `query=`, quedarse con líneas
    del emisor 'Argentina' y, entre ellas, la USD. Devuelve el RIC (ej. ARAE38=,
    040114HS2= para globales). get_history necesita RIC, NO ISIN.
    """
    root = ticker[:-1] if ticker.upper().endswith("D") else ticker
    try:
        r = search.Definition(
            view=search.Views.GOV_CORP_INSTRUMENTS,
            query=root,
            select="DocumentTitle,RIC,ISIN,Currency",
            top=10,
        ).get_data()
        df = r.data.df
    except Exception as e:
        return None, f"search_error:{type(e).__name__}"
    if df is None or not len(df) or "RIC" not in df.columns:
        return None, "no_match"
    rows = [x for x in df.to_dict("records") if x.get("RIC") and str(x["RIC"]) != "<NA>"]
    # Solo emisor soberano argentino (descarta CCGMF/Citi que matchean por ticker).
    arg = [x for x in rows if "Argentina" in str(x.get("DocumentTitle", ""))]
    rows = arg or rows
    usd = [x for x in rows if str(x.get("Currency")) == "USD"]
    rows = usd or rows
    if not rows:
        return None, "no_match"
    return str(rows[0]["RIC"]), "resolved"


def fetch_series(ric, start, end):
    """[{fecha, close, clean, accrued, volume}] o []. `close` es DIRTY (= clean +
    accrued) para alinear con el precio dirty que usa Data912/el monitor."""
    try:
        df = ld.get_history(universe=ric, interval="daily", start=start, end=end)
    except Exception as e:
        print(f"    get_history error {type(e).__name__}: {e}")
        return []
    if df is None or not len(df):
        return []
    cols = list(df.columns)
    # Precio: preferimos DIRTY_PRC; si no, MID_PRICE (clean) + ACCR_INT.
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

    result = {}
    map_dirty = False
    for i, (ticker, info) in enumerate(sorted(ric_map.items()), 1):
        uid = info.get("universe_id")
        if not uid:
            uid, note = resolve(ticker, info.get("isin_local"))
            if uid:
                info["universe_id"] = uid
                map_dirty = True
            else:
                print(f"[{i}/{len(ric_map)}] {ticker}: NO RESUELTO ({note})")
                continue
        series = fetch_series(uid, start, end)
        print(f"[{i}/{len(ric_map)}] {ticker} ({info.get('panel')}): {uid} -> {len(series)} barras")
        if series:
            result[ticker] = {
                "panel": info.get("panel"),
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
