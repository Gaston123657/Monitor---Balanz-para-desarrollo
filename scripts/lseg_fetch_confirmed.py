"""Fetch autoritativo (ref + schedule) de ISINs CONFIRMADOS por el operador para
las ONs que quedaron ambiguas. Salida en el mismo shape que lseg_ons_retry.json
(status=resolved_unique) para reusar scripts/apply_ons_retry.py.

    .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_confirmed.py

Lee data/_ons_confirmed.json = {ticker: isin} y escribe data/lseg_ons_confirmed.json.
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

SEED = ROOT / "data" / "_ons_confirmed.json"
OUT = ROOT / "data" / "lseg_ons_confirmed.json"

REF_FIELDS = ["TR.FiMaturityDate", "TR.FiCouponRate", "TR.FiCouponFrequency",
              "TR.FiIssueDate", "TR.FiIssuerName", "TR.FiCurrency",
              "TR.FiCouponType", "TR.FiDescription", "TR.ISIN",
              "TR.TRBCEconomicSector", "TR.TRBCBusinessSector", "TR.TRBCIndustryGroup"]


def jsonable(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try: return v.item()
        except Exception: pass
    s = v if isinstance(v, (int, float)) else str(v).strip()
    return None if (isinstance(s, str) and not s) else s


def fetch_ref(uid):
    df = ld.get_data(universe=[uid], fields=REF_FIELDS)
    r = df.iloc[0].to_dict()
    ref = {"maturity": jsonable(r.get("Maturity Date")), "coupon_rate": jsonable(r.get("Coupon Rate")),
           "coupon_frequency": jsonable(r.get("Coupon Frequency")), "issue_date": jsonable(r.get("Issue Date")),
           "issuer": jsonable(r.get("Issuer Name")), "currency": jsonable(r.get("Currency")),
           "coupon_type": jsonable(r.get("Coupon Type")), "description": jsonable(r.get("Description")),
           "isin": jsonable(r.get("ISIN")), "trbc_economic": jsonable(r.get("TRBC Economic Sector Name")),
           "trbc_business": jsonable(r.get("TRBC Business Sector Name")),
           "trbc_industry": jsonable(r.get("TRBC Industry Group Name")), "gics": None}
    try:
        g = ld.get_data(universe=[uid], fields=["TR.GICSSector"])
        ref["gics"] = jsonable(g.iloc[0].to_dict().get("GICS Sector Name"))
    except Exception:
        pass
    return ref


def fetch_schedule(uid):
    resp = bond.Definition(instrument_code=uid, notional_amount=100,
                           fields=["CashFlowDatesArray", "CashFlowInterestAmountsInDealCcyArray",
                                   "CashFlowCapitalAmountsInDealCcyArray", "CashFlowTotalAmountsInDealCcyArray"]).get_data()
    df = resp.data.df
    if df is None or not len(df):
        return None
    row = df.iloc[0].to_dict()
    dates = row.get("CashFlowDatesArray")
    if dates is None or (hasattr(dates, "__len__") and len(dates) == 0):
        return None
    intr = row.get("CashFlowInterestAmountsInDealCcyArray") or [0] * len(dates)
    cap = row.get("CashFlowCapitalAmountsInDealCcyArray") or [0] * len(dates)
    tot = row.get("CashFlowTotalAmountsInDealCcyArray") or [0] * len(dates)
    return [{"date": str(d)[:10], "interest": round(float(intr[i]), 6),
             "amortization": round(float(cap[i]), 6), "total": round(float(tot[i]), 6)}
            for i, d in enumerate(dates)]


def main():
    sess = ld.session.desktop.Definition(app_key=os.environ["LSEG_APP_KEY"]).get_session()
    ld.session.set_default(sess); sess.open()
    print("OPEN")
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    out = []
    for tk, isin in seed.items():
        rec = {"ticker": tk, "universe_id": isin, "status": "resolved_unique"}
        try:
            rec["ref"] = fetch_ref(isin)
            if not str(rec["ref"].get("coupon_type") or "").startswith("FR") and rec["ref"].get("currency") != "ARS":
                rec["schedule"] = fetch_schedule(isin)
            print(f"{tk}: {isin} mat={rec['ref'].get('maturity')} cpn={rec['ref'].get('coupon_rate')} "
                  f"flows={len(rec.get('schedule') or [])}")
        except Exception as e:
            rec["status"] = "ref_error"; rec["err"] = str(e)[:120]
            print(f"{tk}: ERR {str(e)[:80]}")
        out.append(rec)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nGuardado {OUT}")
    sess.close()


if __name__ == "__main__":
    main()
