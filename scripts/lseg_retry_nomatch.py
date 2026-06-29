"""Reintento para las 16 ONs que el RIC-search no resolvió: busca en LSEG por
EMISOR (inferido del ticker hermano) y, si queda exactamente UNA serie USD del
emisor que NO esté ya en el master, la toma como la nuestra (match inequívoco).

    .venv-lseg\\Scripts\\python.exe scripts/lseg_retry_nomatch.py

Lee data/_nomatch_seed.json (ticker -> {issuer_query, known_isins_all}) que
genera el py 3.12, y escribe data/lseg_ons_retry.json con ref+schedule para los
que matchean inequívocamente. Los ambiguos se listan para revisión.
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
from lseg.data.content import search

import importlib.util
spec = importlib.util.spec_from_file_location("ffull", ROOT / "scripts" / "lseg_fetch_ons_full.py")
# evitar abrir sesión dos veces: reusamos solo helpers
SEED = ROOT / "data" / "_nomatch_seed.json"
OUT = ROOT / "data" / "lseg_ons_retry.json"

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
    from lseg.data.content.ipa.financial_contracts import bond
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
    print("LSEG session OPEN")
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    known_all = set(seed.get("_known_isins", []))
    results = []
    for tk, info in seed.items():
        if tk.startswith("_"):
            continue
        q = info["issuer_query"]
        try:
            r = search.Definition(view=search.Views.GOV_CORP_INSTRUMENTS,
                                  query=q, filter="IsActive eq true and Currency eq 'USD'",
                                  select="DocumentTitle,RIC,ISIN,MaturityDate,CouponRate,Currency,IssuerName",
                                  top=50).get_data()
            df = r.data.df
        except Exception as e:
            results.append({"ticker": tk, "status": "search_error", "err": str(e)[:120]})
            print(f"{tk}: search_error {str(e)[:80]}"); continue
        cands = df.to_dict("records") if df is not None and len(df) else []
        # 1) filtrar al emisor real (la búsqueda full-text trae ruido) por token
        #    distintivo, 2) excluir ISINs ya en el master, 3) colapsar tranches
        #    144A/RegS del MISMO bono (mismo vto+cupón) en un solo grupo.
        token = info.get("match_token", q.split()[0]).lower()
        fresh, seen, groups = [], set(), {}
        for c in cands:
            isin = str(c.get("ISIN") or "").strip()
            title = str(c.get("DocumentTitle") or "").lower()
            if not isin or isin in known_all or isin in seen or token not in title:
                continue
            seen.add(isin)
            entry = {"isin": isin, "mat": str(c.get("MaturityDate"))[:10],
                     "cpn": c.get("CouponRate"), "title": c.get("DocumentTitle")}
            fresh.append(entry)
            key = (entry["mat"], round(float(c.get("CouponRate") or 0), 3))
            groups.setdefault(key, []).append(entry)
        rec = {"ticker": tk, "issuer_query": q, "n_fresh": len(fresh),
               "n_groups": len(groups), "fresh": fresh}
        if len(groups) == 1:
            uid = next(iter(groups.values()))[0]["isin"]
            try:
                rec["ref"] = fetch_ref(uid)
                ctype = str(rec["ref"].get("coupon_type") or "")
                if not (ctype.startswith("FR") or rec["ref"].get("currency") == "ARS"):
                    rec["schedule"] = fetch_schedule(uid)
                rec["status"] = "resolved_unique"
                print(f"{tk}: UNIQUE -> {uid} mat={rec['ref'].get('maturity')} cpn={rec['ref'].get('coupon_rate')}")
            except Exception as e:
                rec["status"] = "ref_error"; rec["err"] = str(e)[:120]
                print(f"{tk}: ref_error {str(e)[:80]}")
        else:
            rec["status"] = "ambiguous" if groups else "no_fresh"
            print(f"{tk}: {rec['status']} ({len(groups)} distinct bonds / {len(fresh)} ISINs)")
        results.append(rec)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nGuardado {OUT}")
    sess.close()


if __name__ == "__main__":
    main()
