"""Sintéticos de dólar — carry y costo de cobertura sobre futuros DLR.

Cruza la curva de futuros DLR (devaluación implícita) contra la curva de tasa
en pesos (tasa fija), contrato por contrato. Toda la matemática base se reusa
de `core.infrastructure.futures_provider` (`implied_tna`, `parse_contract_maturity`).

Conceptos (todas las tasas son decimales: 0.30 = 30%):

  - **TEA futuro / costo cobertura TEA** = (strike/spot)^(365/días) − 1
    (devaluación implícita anualizada; coincide con el costo de cubrirse en TEA).
  - **vs spot (directo)** = strike/spot − 1 (la brecha directa del contrato).
  - **costo mensual** = (1 + vs_spot)^(30/días) − 1 (prorrateo mensual compuesto
    del costo directo — sólo se materializa si la brecha contra el spot ocurre).
  - **TEA pesos (curva)** = curva NSS de tasa fija evaluada al tenor del contrato.
  - **carry** = TEA pesos − TEA futuro (en decimal; >0 ⇒ el peso rinde más que la
    devaluación implícita, carry positivo a favor de tasa en pesos).
  - **basis $** = strike − spot.

El bundle `peso_curve` es un objeto Python (no JSON): producido por el motor BEI
(`compute_bei_tables`) y cacheado en proceso:

    {
      "curve":       callable(t_years) -> tasa decimal,   # NSS/NS/lineal
      "t_range":     (lo_years, hi_years),                # rango observado
      "instruments": [(years, ticker, tir_decimal), ...], # tasa fija para 'nearest'
    }
"""

from datetime import date
from typing import Dict, List, Optional

from core.infrastructure.futures_provider import implied_tna, parse_contract_maturity

# Meses abreviados ESP, alineados con los sufijos de ticker de Matba (JUN26).
_MONTHS_ABBR = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def contract_label(symbol: str, mat: Optional[date]) -> str:
    """`DLR/JUN26` -> `jun-26`. Cae al sufijo crudo si no hay vto parseable."""
    if mat is not None:
        return f"{_MONTHS_ABBR[mat.month]}-{mat.year % 100:02d}"
    return symbol.split("/")[-1].lower()


def _tea_to_tna(tea: Optional[float]) -> Optional[float]:
    """TEA → TNA base 365 (diaria capitalizada): 365·((1+TEA)^(1/365) − 1).
    Misma convención que `FinancialEngine.tea_to_tna` / `tna_sint`."""
    if tea is None:
        return None
    try:
        return 365.0 * ((1.0 + tea) ** (1.0 / 365.0) - 1.0)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _eval_peso_curve(peso_curve: Optional[dict], years: float) -> Optional[float]:
    """Evalúa la curva de pesos al tenor `years`, sólo dentro de ±10% del rango
    observado (evita extrapolación salvaje de NSS, mismo criterio que el BEI)."""
    if not peso_curve or years <= 0:
        return None
    curve = peso_curve.get("curve")
    if curve is None:
        return None
    lo, hi = peso_curve.get("t_range", (None, None))
    if lo is None or hi is None or years < lo * 0.9 or years > hi * 1.1:
        return None
    try:
        return float(curve(years))
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _nearest_instrument(peso_curve: Optional[dict], years: float):
    """Instrumento tasa fija con vto más cercano al tenor del contrato.
    Devuelve (ticker, tir_decimal) o (None, None)."""
    if not peso_curve:
        return None, None
    insts = peso_curve.get("instruments") or []
    best = None
    best_diff = None
    for t_years, ticker, tir in insts:
        if tir is None or t_years is None:
            continue
        diff = abs(t_years - years)
        if best_diff is None or diff < best_diff:
            best, best_diff = (ticker, tir), diff
    if best is None:
        return None, None
    return best[0], best[1]


def build_synthetic_rows(
    quotes: Dict[str, dict],
    symbols: List[str],
    spot: Optional[float],
    today: date,
    peso_curve: Optional[dict],
) -> List[dict]:
    """Una fila por contrato DLR con datos vivos. Tasas en decimal, sin escalar.

    Omite contratos sin precio (`last`/`settle`/`prev_settle`), sin vto, o ya
    vencidos (días<=0). Si falta el spot devuelve [] (sin spot no hay sintético).
    """
    if not spot or spot <= 0:
        return []
    rows: List[dict] = []
    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            continue
        mat = parse_contract_maturity(sym)
        if mat is None:
            continue
        days = (mat - today).days
        if days <= 0:
            continue
        strike = q.get("last") or q.get("settle") or q.get("prev_settle")
        if not strike or strike <= 0:
            continue

        tea_fut = implied_tna(strike, spot, mat, today)
        vs_spot = strike / spot - 1.0
        try:
            costo_mensual = (1.0 + vs_spot) ** (30.0 / days) - 1.0
        except (ValueError, OverflowError, ZeroDivisionError):
            costo_mensual = None

        years = days / 365.25
        tea_pesos = _eval_peso_curve(peso_curve, years)
        carry = (tea_pesos - tea_fut) if (tea_pesos is not None and tea_fut is not None) else None

        inst_ticker, tea_pesos_inst = _nearest_instrument(peso_curve, years)
        carry_inst = (
            tea_pesos_inst - tea_fut
            if (tea_pesos_inst is not None and tea_fut is not None) else None
        )

        rows.append({
            "ticker": sym,
            "label": contract_label(sym, mat),
            "vto": mat,
            "dias": days,
            "strike": strike,
            "spot": spot,
            "tea_fut": tea_fut,
            "vs_spot": vs_spot,
            "costo_mensual": costo_mensual,
            "tea_pesos": tea_pesos,
            "carry": carry,
            "inst_ticker": inst_ticker,
            "tea_pesos_inst": tea_pesos_inst,
            "carry_inst": carry_inst,
            "basis": strike - spot,
            "open_interest": q.get("open_interest"),
            "volume": q.get("volume"),
        })
    rows.sort(key=lambda r: r["dias"])
    return rows


def _nearest_future(
    quotes: Dict[str, dict],
    symbols: List[str],
    target_mat: date,
    today: date,
    max_gap_days: Optional[int],
):
    """Contrato de futuro DLR cuyo vencimiento está más cerca de `target_mat`
    (calce con el dólar-linked). Devuelve (symbol, mat, strike, gap_dias) o
    (None, None, None, None) si ninguno cae dentro de `max_gap_days`."""
    best = None
    best_gap = None
    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            continue
        mat = parse_contract_maturity(sym)
        if mat is None or (mat - today).days <= 0:
            continue
        strike = q.get("last") or q.get("settle") or q.get("prev_settle")
        if not strike or strike <= 0:
            continue
        gap = abs((mat - target_mat).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = (sym, mat, strike), gap
    if best is None or (max_gap_days is not None and best_gap > max_gap_days):
        return None, None, None, None
    return best[0], best[1], best[2], best_gap


def build_dl_synthetic_rows(
    dl_specs: List[dict],
    quotes: Dict[str, dict],
    symbols: List[str],
    spot: Optional[float],
    today: date,
    peso_curve: Optional[dict],
    max_gap_days: Optional[int] = 45,
) -> List[dict]:
    """Sintético de tasa en pesos = comprar un dólar-linked + vender (short) un
    contrato de dólar futuro con vencimiento calzado.

    Las dos exposiciones al TC oficial se cancelan y queda una tasa fija en
    pesos conocida hoy. Con par del DL = 100 USD (misma convención que el
    `FinancialEngine`: el DL paga 100 USD al vto), invertís `price` pesos y
    cobrás `100 × strike` pesos a `d` días:

        tasa_sintetica_TEA = (100 × F / P_dl)^(365/d) − 1
        tasa_sintetica_TNA = 365 × ((100 × F / P_dl)^(1/d) − 1)

    El spot **se cancela** algebraicamente (no entra en la tasa sintética): el
    DL paga 100·A3500(T) y el short del futuro cambia A3500(T) por F. Sólo se
    usa el spot para columnas de contexto (deval implícita del futuro, TIR USD
    del DL), que cumplen la identidad:

        (1 + tasa_sintetica) = (1 + tir_dl_USD) · (1 + tea_futuro)

    `dl_specs`: lista de dicts {ticker, maturity (date), price (pesos)}. Cada DL
    se calza con el futuro de vto más cercano (dentro de `max_gap_days`). El
    spread se computa contra la curva de tasa fija (LECAP/BONCAP) y contra el
    bono fija de plazo más cercano. Tasas en decimal (0.30 = 30%).
    """
    rows: List[dict] = []
    for spec in dl_specs:
        ticker = spec.get("ticker")
        mat = spec.get("maturity")
        price = spec.get("price")
        if not ticker or mat is None or not price or price <= 0:
            continue
        days = (mat - today).days
        if days <= 0:
            continue

        fut_sym, fut_mat, strike, gap = _nearest_future(
            quotes, symbols, mat, today, max_gap_days
        )
        if strike is None:
            continue

        try:
            growth = (100.0 * strike) / price
            tea_sint = growth ** (365.0 / days) - 1.0
            tna_sint = 365.0 * (growth ** (1.0 / days) - 1.0)
        except (ValueError, OverflowError, ZeroDivisionError):
            continue

        # Contexto (no entran en la tasa sintética): deval implícita del futuro
        # y TIR en USD del DL. Cumplen (1+sint) = (1+tir_dl)·(1+tea_fut).
        tea_fut = implied_tna(strike, spot, fut_mat, today) if spot else None
        tir_dl = None
        if spot and spot > 0:
            try:
                tir_dl = (100.0 * spot / price) ** (365.0 / days) - 1.0
            except (ValueError, OverflowError, ZeroDivisionError):
                tir_dl = None

        years = days / 365.25
        tea_fija = _eval_peso_curve(peso_curve, years)
        spread = (tea_sint - tea_fija) if tea_fija is not None else None

        inst_ticker, tea_fija_inst = _nearest_instrument(peso_curve, years)
        spread_inst = (
            tea_sint - tea_fija_inst if tea_fija_inst is not None else None
        )

        # TNA equivalentes (base 365, capitalización diaria) — usadas por el
        # gráfico del panel, que se muestra en TNA. El spread en pp es el mismo
        # en cualquier convención de las tasas sintética/fija comparadas, pero
        # acá derivamos también los spreads en TNA por consistencia visual.
        tna_fija = _tea_to_tna(tea_fija)
        tna_fija_inst = _tea_to_tna(tea_fija_inst)
        spread_tna = (
            _tea_to_tna(tea_sint) - tna_fija
            if (tna_fija is not None) else None
        )
        spread_inst_tna = (
            _tea_to_tna(tea_sint) - tna_fija_inst
            if (tna_fija_inst is not None) else None
        )

        rows.append({
            "ticker": ticker,
            "vto": mat,
            "dias": days,
            "fut_ticker": fut_sym,
            "fut_label": contract_label(fut_sym, fut_mat),
            "fut_vto": fut_mat,
            "gap_dias": gap,
            "strike": strike,
            "price": price,
            "tea_sint": tea_sint,
            "tna_sint": tna_sint,
            "tea_fut": tea_fut,
            "tir_dl": tir_dl,
            "tea_fija": tea_fija,
            "tna_fija": tna_fija,
            "spread": spread,
            "spread_tna": spread_tna,
            "inst_ticker": inst_ticker,
            "tea_fija_inst": tea_fija_inst,
            "tna_fija_inst": tna_fija_inst,
            "spread_inst": spread_inst,
            "spread_inst_tna": spread_inst_tna,
        })
    rows.sort(key=lambda r: r["dias"])
    return rows
