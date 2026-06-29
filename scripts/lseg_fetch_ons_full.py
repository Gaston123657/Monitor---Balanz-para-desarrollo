"""Paso 2/3 (full): baja de LSEG ref-data + sector TRBC + schedule de cashflows
para TODAS las ONs incompletas (data/_ons_incomplete.json).

Corre en el venv AISLADO con Workspace Desktop ABIERTO y LOGUEADO:

    .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_ons_full.py

Reusa la resolución ticker->instrumento de lseg_fetch_ons.py (ISIN local si
existe; si no, RIC search 'AR<root>' en GovCorpInstruments). Para cada ON baja:
  - ref: emisor, moneda, ISIN, vto, cupón, frecuencia, emisión, coupon_type
  - sector: TRBC Economic/Business + GICS (fallback) -> mapeo a taxonomía
    Balanz se hace en el apply
  - schedule de cashflows exacto vía IPA (notional=100) -> para derivar
    bullet/amortizing y el calendario

Salida: data/lseg_ons_full.json (lo consume scripts/apply_ons_full.py).
Day-count (base calculo) y legislacion NO vienen de LSEG (TR.FiGoverningLaw y
los TR.FiDayCount* no resuelven) -> se derivan en el apply desde el ISIN.
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
from lseg.data.content.ipa.financial_contracts import bond

INP = ROOT / "data" / "_ons_incomplete.json"
OUT = ROOT / "data" / "lseg_ons_full.json"

REF_FIELDS = ["TR.FiMaturityDate", "TR.FiCouponRate", "TR.FiCouponFrequency",
              "TR.FiIssueDate", "TR.FiIssuerName", "TR.FiCurrency",
              "TR.FiCouponType", "TR.FiDescription", "TR.ISIN",
              "TR.TRBCEconomicSector", "TR.TRBCBusinessSector",
              "TR.TRBCIndustryGroup"]


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


def resolve(ticker, isin_local):
    """(universe_id, candidates, note). Igual criterio que lseg_fetch_ons.py."""
    if isin_local:
        return isin_local, [{"via": "isin_local", "id": isin_local}], "isin_local"
    root = ticker[:-1]
    try:
        r = search.Definition(
            view=search.Views.GOV_CORP_INSTRUMENTS,
            filter=f"startswith(RIC,'AR{root}')",
            select="DocumentTitle,RIC,ISIN,MaturityDate,CouponRate,Currency",
            top=25,
        ).get_data()
        df = r.data.df
    except Exception as e:
        return None, [{"error": f"{type(e).__name__}: {e}"}], "search_error"
    if df is None or not len(df):
        return None, [], "no_match"
    cands = df.to_dict("records")

    def extra(ric):
        ric = str(ric or "")
        stem = ric[2:].split("=", 1)[0]
        return stem[len(root):] if stem.startswith(root) else None
    tight = [c for c in cands if (e := extra(c.get("RIC"))) is not None and len(e) <= 2]
    pool = tight or cands
    isins = {str(c.get("ISIN")) for c in pool if c.get("ISIN")}
    if len(isins) > 1:
        usd = [c for c in pool if str(c.get("Currency")) == "USD"]
        if len({str(c.get("ISIN")) for c in usd}) == 1:
            pool = usd
        else:
            return None, cands, "ambiguous"
    pool = sorted(pool, key=lambda c: (0 if str(c.get("RIC", "")).endswith("=BA") else 1,
                                       len(str(c.get("RIC") or "zzz"))))
    chosen = pool[0]
    uid = chosen.get("ISIN") or chosen.get("RIC")
    return uid, cands, "resolved"


def fetch_ref(uid):
    df = ld.get_data(universe=[uid], fields=REF_FIELDS)
    row = df.iloc[0].to_dict()
    ref = {
        "maturity": jsonable(row.get("Maturity Date")),
        "coupon_rate": jsonable(row.get("Coupon Rate")),
        "coupon_frequency": jsonable(row.get("Coupon Frequency")),
        "issue_date": jsonable(row.get("Issue Date")),
        "issuer": jsonable(row.get("Issuer Name")),
        "currency": jsonable(row.get("Currency")),
        "coupon_type": jsonable(row.get("Coupon Type")),
        "description": jsonable(row.get("Description")),
        "isin": jsonable(row.get("ISIN")),
        "trbc_economic": jsonable(row.get("TRBC Economic Sector Name")),
        "trbc_business": jsonable(row.get("TRBC Business Sector Name")),
        "trbc_industry": jsonable(row.get("TRBC Industry Group Name")),
    }
    # GICS por separado (suele tirar "unable to resolve identifier" para algunos).
    try:
        g = ld.get_data(universe=[uid], fields=["TR.GICSSector"])
        ref["gics"] = jsonable(g.iloc[0].to_dict().get("GICS Sector Name"))
    except Exception:
        ref["gics"] = None
    return ref


def fetch_schedule(uid):
    resp = bond.Definition(
        instrument_code=uid, notional_amount=100,
        fields=["CashFlowDatesArray", "CashFlowInterestAmountsInDealCcyArray",
                "CashFlowCapitalAmountsInDealCcyArray", "CashFlowTotalAmountsInDealCcyArray"],
    ).get_data()
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
    out = []
    for i, d in enumerate(dates):
        out.append({
            "date": str(d)[:10],
            "interest": round(float(intr[i]), 6),
            "amortization": round(float(cap[i]), 6),
            "total": round(float(tot[i]), 6),
        })
    return out


def main():
    sess = ld.session.desktop.Definition(app_key=os.environ["LSEG_APP_KEY"]).get_session()
    ld.session.set_default(sess); sess.open()
    print("LSEG session OPEN")

    targets = json.loads(INP.read_text(encoding="utf-8"))
    print(f"ONs incompletas a resolver: {len(targets)}")

    results = []
    for i, t in enumerate(targets, 1):
        tk = t["ticker"]
        uid, cands, note = resolve(tk, t.get("isin_local"))
        rec = {**t, "universe_id": uid, "resolve_note": note,
               "n_candidates": len(cands), "candidates": cands,
               "ref": None, "schedule": None, "status": note}
        if not uid:
            print(f"[{i}/{len(targets)}] {tk}: {note.upper()} ({len(cands)} cands)")
            results.append(rec); continue
        try:
            rec["ref"] = fetch_ref(uid)
        except Exception as e:
            rec["status"] = "ref_error"
            print(f"[{i}/{len(targets)}] {tk}: {uid} REF ERR {type(e).__name__}: {str(e)[:80]}")
            results.append(rec); continue

        ref = rec["ref"]
        ctype = str(ref.get("coupon_type") or "")
        floating = ctype.startswith("FR") or ref.get("currency") == "ARS"
        if not floating:
            try:
                rec["schedule"] = fetch_schedule(uid)
            except Exception as e:
                rec["schedule_error"] = f"{type(e).__name__}: {e}"
        rec["status"] = "ok" if ref.get("maturity") else "ref_partial"
        sec = ref.get("trbc_economic") or ref.get("gics") or "?"
        print(f"[{i}/{len(targets)}] {tk}: {uid} mat={ref.get('maturity')} "
              f"cpn={ref.get('coupon_rate')} freq={ref.get('coupon_frequency')} "
              f"sec={sec} flows={len(rec['schedule']) if rec['schedule'] else 0}")
        results.append(rec)

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    from collections import Counter
    print(f"\nGuardado {OUT}")
    print("Resumen:", dict(Counter(r["status"] for r in results)))
    sess.close()


if __name__ == "__main__":
    main()
