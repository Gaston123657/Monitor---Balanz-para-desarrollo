"""Break-Even Inflation monitor — BCRA Nota Técnica N°8/2024.

Fits Nelson-Siegel curves to nominal (LECAP/BONCAP) and real (CER) yields,
then applies Fisher parity to estimate expected inflation at standard tenors.
The lag-adjusted column strips already-known CER variation (γ factor).
"""

import logging
from datetime import date, datetime, timedelta

import pandas as pd

from apps.cli.monitors._common import build_use_case, fmt_pct, save_report
from core.domain.instrument_groups import CER, TASA_FIJA
from core.domain.yield_curve import (
    NelsonSiegelCurve,
    forward_bei,
    gamma_known_cer_factor,
)
from core.holiday_engine import settlement_byma
from core.infrastructure.indices_provider import BCRAIndicesProvider

logger = logging.getLogger(__name__)

# Plazos estándar a reportar (en años).
_TENORS = [
    ("3M", 0.25),
    ("6M", 0.50),
    ("9M", 0.75),
    ("1Y", 1.00),
    ("18M", 1.50),
    ("2Y", 2.00),
    ("3Y", 3.00),
]


def _curve_points(metrics_list, today):
    """Return [(years_to_maturity, tir_decimal)] for usable bonds."""
    points = []
    for m in metrics_list:
        inst = m.snapshot.instrument
        if m.tir is None or inst is None or inst.maturity_date is None:
            continue
        years = (inst.maturity_date - today).days / 365.25
        if years <= 0 or m.tir < -0.5 or m.tir > 5.0:
            continue
        points.append((years, m.tir))
    return points


def _gamma_factor(indices_provider, settle_date) -> float | None:
    """γ = CER_ULT / CER_LIQ-10h. Walk back 10 business days for the lag."""
    # CER at settle minus 10 business days
    from core.holiday_engine import is_habil
    target = settle_date
    count = 0
    while count < 10:
        target -= timedelta(days=1)
        if is_habil(target.strftime("%Y-%m-%d")):
            count += 1
    cer_liq_10h = indices_provider.get_cer(target)
    cer_last = indices_provider.get_cer(date.today())
    return gamma_known_cer_factor(cer_liq_10h, cer_last)


def generate_bei_report(output_dir: str):
    logger.info("Generando reporte de BEI (Break-Even Inflation)...")
    use_case = build_use_case()
    today = datetime.now().date()

    nominal_points = _curve_points(use_case.execute(TASA_FIJA), today)
    real_points = _curve_points(use_case.execute(CER), today)

    if len(nominal_points) < 3 or len(real_points) < 3:
        logger.error(
            f"Datos insuficientes: nominal={len(nominal_points)} CER={len(real_points)} "
            "(se requieren >=3 puntos en cada curva)."
        )
        return None

    try:
        nom_curve = NelsonSiegelCurve.fit(*zip(*nominal_points))
        real_curve = NelsonSiegelCurve.fit(*zip(*real_points))
    except (ValueError, RuntimeError) as e:
        logger.error(f"Fallo el ajuste Nelson-Siegel: {e}")
        return None

    # Lag adjustment (gamma factor)
    indices = BCRAIndicesProvider()
    settle_date = settlement_byma(today.strftime("%Y-%m-%d"), lag=1).date()
    gamma = _gamma_factor(indices, settle_date)
    if gamma is None:
        logger.warning("No se pudo obtener γ — BEI ajustada por lag no disponible.")

    rows = []
    for label, years in _TENORS:
        i_nom = nom_curve(years)
        r_real = real_curve(years)
        bei_spot = forward_bei(i_nom, r_real)
        bei_fwd = forward_bei(i_nom, r_real, gamma=gamma) if gamma else None
        rows.append({
            "Plazo": label,
            "Dias": int(round(years * 365)),
            "TEA Nominal": fmt_pct(i_nom, scale=100.0),
            "TEA Real": fmt_pct(r_real, scale=100.0),
            "BEI spot": fmt_pct(bei_spot, scale=100.0),
            "BEI fwd (gamma-adj)": fmt_pct(bei_fwd, scale=100.0) if bei_fwd is not None else "-",
        })

    df = pd.DataFrame(rows)
    nom_n = len(nominal_points)
    real_n = len(real_points)
    gamma_s = f"{gamma:.4f}" if gamma else "n/d"
    title = (
        f"BREAK-EVEN INFLATION - Fisher + Nelson-Siegel  "
        f"[LECAP n={nom_n} | CER n={real_n} | gamma={gamma_s}]"
    )
    return save_report(df, output_dir, "monitor_bei", title)
