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
