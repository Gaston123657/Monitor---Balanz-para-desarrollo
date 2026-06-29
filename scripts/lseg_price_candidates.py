"""Para las ONs ambiguas: baja de LSEG precio de mercado (TR.FiPrice) y TIR
implícita (IPA yield-from-price) de cada serie candidata, para que el operador
confirme el match contra el precio data912. NO escribe nada en el master.

    .venv-lseg\\Scripts\\python.exe scripts/lseg_price_candidates.py

Lee data/lseg_ons_retry.json (candidatos por ticker) y escribe
data/lseg_candidate_prices.json. El armado de la tabla final (+ precio data912)
lo hace scripts/show_candidate_table.py (py 3.12).
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

import lseg.data as ld
from lseg.data.content.ipa.financial_contracts import bond

RETRY = ROOT / "data" / "lseg_ons_retry.json"
D912 = ROOT / "data" / "_data912_px.json"
OUT = ROOT / "data" / "lseg_candidate_prices.json"
SKIP = {"CLI1D", "CLSID"}  # CLISA reestructurada -> aparte


def num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def get_price(isin):
    try:
        df = ld.get_data(universe=[isin], fields=["TR.FiPrice"])
        return num(df.iloc[0].to_dict().get("Price"))
    except Exception:
        return None


def get_yield(isin, clean_price):
    """TIR implícita al precio dado (IPA). Si no hay precio, devuelve la teórica."""
    try:
        pp = bond.PricingParameters(clean_price=clean_price) if clean_price is not None else None
        kw = {"instrument_code": isin, "notional_amount": 100,
              "fields": ["YieldPercent", "DirtyPrice", "AccruedPercent"]}
        if pp is not None:
            kw["pricing_parameters"] = pp
        resp = bond.Definition(**kw).get_data()
        r = resp.data.df.iloc[0].to_dict()
        return num(r.get("Yield Percent") or r.get("YieldPercent")), num(r.get("Dirty Price") or r.get("DirtyPrice"))
    except Exception as e:
        return None, None


def main():
    sess = ld.session.desktop.Definition(app_key=os.environ["LSEG_APP_KEY"]).get_session()
    ld.session.set_default(sess); sess.open()
    print("OPEN")
    recs = {r["ticker"]: r for r in json.loads(RETRY.read_text(encoding="utf-8"))}
    d912 = json.loads(D912.read_text(encoding="utf-8")) if D912.exists() else {}
    out = {}
    for tk, r in recs.items():
        if tk in SKIP or r.get("status") != "ambiguous":
            continue
        px_local = num(d912.get(tk))
        # colapsar tranches por (vto, cupón); quedarse con un ISIN representativo
        groups = {}
        for c in r.get("fresh", []):
            key = (c["mat"], round(float(c["cpn"] or 0), 3))
            groups.setdefault(key, c)
        rows = []
        for (mat, cpn), c in sorted(groups.items()):
            isin = c["isin"]
            px = get_price(isin)
            ytm, dirty = get_yield(isin, px)
            # TIR implícita al precio LOCAL data912 (discriminador del match)
            tir_local, _ = get_yield(isin, px_local) if px_local is not None else (None, None)
            rows.append({"isin": isin, "mat": mat, "cpn": cpn,
                         "lseg_price": px, "tir_lseg": ytm,
                         "data912_price": px_local, "tir_at_data912": tir_local})
            print(f"{tk} {isin} vto={mat} cpn={cpn} lseg_px={px} tir_lseg={ytm} "
                  f"d912={px_local} tir@d912={tir_local}")
        out[tk] = rows
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado {OUT}")
    sess.close()


if __name__ == "__main__":
    main()
