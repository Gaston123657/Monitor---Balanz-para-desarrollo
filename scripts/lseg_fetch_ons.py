"""Resuelve y baja datos de LSEG Workspace para las ONs sin datos del monitor.

Corre en el venv AISLADO (pandas<3, ver LSEG-WORKSPACE-README.txt):

    .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_ons.py

REQUISITO: LSEG Workspace Desktop ABIERTO y LOGUEADO (Desktop Session,
handshake localhost:9000).

QUÉ HACE
--------
1. Lee data/_ons_missing.json (lista de ONs sin vto/cupón/frecuencia,
   generada con `py -3.12 scripts/_dump_missing.py`).
2. Resuelve cada ticker local Balanz -> instrumento LSEG. El ticker local
   (ej. AERBD) NO es identificador LSEG, pero la línea BA-listada tiene RIC
   con patrón 'AR<root><clase>=...' donde root = ticker sin el sufijo de
   moneda (D). Se filtra por startswith(RIC,'AR<root>') en GovCorpInstruments.
   - El root de 4 chars es específico: devuelve la serie exacta (o varias
     líneas de settlement del MISMO ISIN). Si aparecen ISINs distintos ->
     se marca 'ambiguous' y NO se adivina.
3. Baja reference data (vto/cupón/frecuencia/emisión/emisor/moneda/ISIN).
4. Baja el SCHEDULE DE CASHFLOWS exacto vía IPA (notional=100), que captura
   amortización/zero-coupon/step-up sin depender de campos poco fiables
   (TR.FiAmortizationType viene vacío incluso para bonos amortizing).
   IPA precia a hoy => devuelve solo flujos FUTUROS (justo lo que el
   calendario necesita).

Guarda TODO (resuelto, ambiguo, no resuelto, floating) en
data/lseg_ons_cache.json. A partir de ahí el monitor usa el cache (lo aplica
`scripts/apply_lseg_ons.py` con py 3.12) y NO depende más de la API.

Floating Rate Notes (FRN, cupón variable BADLAR/etc.) e instrumentos en ARS
no se pueden estimar como flujos fijos: se marcan y se omiten.
"""
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

import lseg.data as ld
from lseg.data.content import search
from lseg.data.content.ipa.financial_contracts import bond

MISSING = ROOT / "data" / "_ons_missing.json"
OUT = ROOT / "data" / "lseg_ons_cache.json"

REF_FIELDS = ["TR.FiMaturityDate", "TR.FiCouponRate", "TR.FiCouponFrequency",
              "TR.FiIssueDate", "TR.FiIssuerName", "TR.FiCurrency",
              "TR.FiCouponType", "TR.FiDescription", "TR.ISIN"]


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
    return v


def resolve(ticker, isin_local):
    """Devuelve (universe_id, candidates, note). universe_id es ISIN o RIC para
    consultar; None si no se resuelve o es ambiguo."""
    if isin_local:
        return isin_local, [{"via": "isin_local", "id": isin_local}], "isin_local"
    root = ticker[:-1]  # quita el sufijo de moneda (D)
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
    # Quedarse con líneas cuyo RIC = AR<root><clase corta>=...  (clase 1-2 chars).
    # Descarta series donde root es solo un prefijo de otra (root más largo).
    def extra(ric):
        ric = str(ric or "")
        stem = ric[2:].split("=", 1)[0]           # quita 'AR' y el sufijo '=...'
        return stem[len(root):] if stem.startswith(root) else None
    tight = [c for c in cands if (e := extra(c.get("RIC"))) is not None and len(e) <= 2]
    pool = tight or cands
    isins = {str(c.get("ISIN")) for c in pool if c.get("ISIN")}
    if len(isins) > 1:
        # Desempate: los tickers D son hard-dollar. Si exactamente una línea es
        # USD, es la correcta; sino es genuinamente ambiguo y NO se adivina.
        usd = [c for c in pool if str(c.get("Currency")) == "USD"]
        if len({str(c.get("ISIN")) for c in usd}) == 1:
            pool = usd
        else:
            return None, cands, "ambiguous"
    # Preferir la línea =BA (BA-listada) o la de RIC más corto; usar ISIN como id.
    pool = sorted(pool, key=lambda c: (0 if str(c.get("RIC", "")).endswith("=BA") else 1,
                                       len(str(c.get("RIC") or "zzz"))))
    chosen = pool[0]
    uid = chosen.get("ISIN") or chosen.get("RIC")
    return uid, cands, "resolved"


def fetch_ref(uid):
    df = ld.get_data(universe=[uid], fields=REF_FIELDS)
    row = df.iloc[0].to_dict()
    return {
        "maturity": jsonable(row.get("Maturity Date")),
        "coupon_rate": jsonable(row.get("Coupon Rate")),
        "coupon_frequency": jsonable(row.get("Coupon Frequency")),
        "issue_date": jsonable(row.get("Issue Date")),
        "issuer": jsonable(row.get("Issuer Name")),
        "currency": jsonable(row.get("Currency")),
        "coupon_type": jsonable(row.get("Coupon Type")),
        "description": jsonable(row.get("Description")),
        "isin": jsonable(row.get("ISIN")),
    }


def fetch_schedule(uid):
    """Schedule de flujos futuros per-100. Devuelve lista de
    {date, amortization, interest, total} o None si IPA no puede (FRN, etc.)."""
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

    targets = json.loads(MISSING.read_text(encoding="utf-8"))
    print(f"ONs sin datos a resolver: {len(targets)}")

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
            ref = fetch_ref(uid)
            rec["ref"] = ref
        except Exception as e:
            rec["status"] = "ref_error"
            print(f"[{i}/{len(targets)}] {tk}: {uid} REF ERR {type(e).__name__}: {e}")
            results.append(rec); continue

        # Floating / ARS -> no estimable como flujo fijo.
        ctype = str(ref.get("coupon_type") or "")
        if ctype.startswith("FR") or ref.get("currency") == "ARS":
            rec["status"] = "floating"
            print(f"[{i}/{len(targets)}] {tk}: {uid} FLOATING/ARS (ctype={ctype} ccy={ref.get('currency')})")
            results.append(rec); continue

        try:
            sched = fetch_schedule(uid)
        except Exception as e:
            sched = None
            rec["schedule_error"] = f"{type(e).__name__}: {e}"
        if not sched:
            rec["status"] = "no_schedule"
            print(f"[{i}/{len(targets)}] {tk}: {uid} mat={ref['maturity']} NO SCHEDULE")
            results.append(rec); continue

        rec["schedule"] = sched
        rec["status"] = "ok"
        cap_sum = round(sum(c["amortization"] for c in sched), 2)
        print(f"[{i}/{len(targets)}] {tk}: {uid} mat={ref['maturity']} cpn={ref['coupon_rate']} "
              f"freq={ref['coupon_frequency']} flows={len(sched)} cap_sum={cap_sum}")
        results.append(rec)

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    from collections import Counter
    c = Counter(r["status"] for r in results)
    print(f"\nGuardado {OUT}")
    print("Resumen:", dict(c))
    sess.close()


if __name__ == "__main__":
    main()
