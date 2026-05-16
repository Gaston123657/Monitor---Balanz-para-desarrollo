import logging
from datetime import date, timedelta
from typing import List, Optional

import numpy as np
from scipy.optimize import brentq, newton

from core.domain.models import MarketSnapshot
from core.holiday_engine import is_habil, settlement_byma

logger = logging.getLogger(__name__)


def _is_cer_type(instrument_type: str) -> bool:
    # CER-adjusted bonds in the master Excel use several `tipo` values that
    # don't all contain the substring "CER" (DICP/CUAP are "CON CUPON";
    # PARP is "STEP-UP"). All belong to the CER sheet — match the union.
    return any(token in instrument_type for token in ("CER", "CON CUPON", "STEP-UP"))


def _is_dolar_linked_type(instrument_type: str) -> bool:
    return "DOLAR_LINKED" in instrument_type or "DOLAR LINKED" in instrument_type


def _is_tamar_puro_type(instrument_type: str) -> bool:
    return instrument_type.upper().strip() == "PURO"


def _is_dual_tamar_type(instrument_type: str) -> bool:
    return instrument_type.upper().strip() == "DUAL"


def _tamar_daily_factor(tna_pct: Optional[float]) -> Optional[float]:
    """BCRA TAMAR is TNA in percent units. Daily compounding factor = 1 + TNA/100/365."""
    if tna_pct is None:
        return None
    return 1.0 + (tna_pct / 100.0) / 365.0


def _fixed_daily_factor_from_monthly(floor_monthly: Optional[float]) -> Optional[float]:
    """Convert TEM (monthly effective rate, decimal) to daily factor: (1+TEM)^(1/30)."""
    if floor_monthly is None or floor_monthly <= -1:
        return None
    try:
        return (1.0 + floor_monthly) ** (1.0 / 30.0)
    except (ValueError, OverflowError):
        return None


def _accrued_tamar_factor(emission: date, end: date, tamar_provider) -> Optional[float]:
    """Compound daily TAMAR from emission to `end`. Returns multiplicative factor.

    Missing daily values are filled by the 14-day backward lookup that
    `BCRAIndicesProvider.get_tamar` already performs (weekends + holidays
    inherit the previous business-day rate, which matches market convention).
    """
    if not emission or end <= emission:
        return 1.0
    factor = 1.0
    d = emission
    one_day = timedelta(days=1)
    while d < end:
        df = _tamar_daily_factor(tamar_provider.get_tamar(d))
        if df:
            factor *= df
        d = d + one_day
    return factor


def _accrued_dual_factor(emission: date, end: date, floor_monthly: float, tamar_provider) -> Optional[float]:
    """Compound daily max(TAMAR_daily, fixed_daily) from emission to `end`."""
    fixed_daily = _fixed_daily_factor_from_monthly(floor_monthly)
    if not emission or end <= emission or fixed_daily is None:
        return 1.0
    factor = 1.0
    d = emission
    one_day = timedelta(days=1)
    while d < end:
        tamar_df = _tamar_daily_factor(tamar_provider.get_tamar(d)) or 1.0
        factor *= max(tamar_df, fixed_daily)
        d = d + one_day
    return factor


def _settlement_for(instrument_type: str) -> date:
    lag = 0 if any(t in instrument_type for t in ("LECER", "LECAP", "CI")) else 1
    return settlement_byma(date.today().strftime("%Y-%m-%d"), lag=lag).date()


def _cer_reference_date(settle: date, lag_business_days: int) -> date:
    target = settle
    count = 0
    while count < lag_business_days:
        target -= timedelta(days=1)
        if is_habil(target.strftime("%Y-%m-%d")):
            count += 1
    return target


class FinancialEngine:
    @staticmethod
    def xirr(flows: List[float], dates: List[date]) -> float:
        if not flows or len(flows) < 2:
            return np.nan

        d0 = dates[0]
        years = np.array([(d - d0).days / 365.25 for d in dates])
        flows = np.array(flows)

        def npv(rate):
            if rate <= -1.0:
                return 1e12
            return np.sum(flows / (1 + rate) ** years)

        for guess in (0.05, 0.2, -0.1, 0.8, -0.5):
            try:
                res = newton(npv, guess, maxiter=50)
                if not np.isnan(res) and abs(npv(res)) < 1e-4:
                    return res
            except (RuntimeError, ValueError, OverflowError):
                continue

        try:
            return brentq(npv, -0.999, 10.0)
        except (RuntimeError, ValueError):
            return np.nan

    @staticmethod
    def calculate_technical_value(snapshot: MarketSnapshot, indices_provider) -> float:
        """Valor Técnico (Valor Par) for CER bonds; 100.0 otherwise.

        Per BCRA Nota Técnica N°8/2024, the indexation factor is CER_LIQ-10h
        over CER_BASE (where BASE = CER 10 business days before emission, stored
        in `inst.cer_base`). For amortizing bonds, residual principal already
        paid down is excluded.
        """
        inst = snapshot.instrument
        if not inst or not _is_cer_type(inst.instrument_type):
            return 100.0

        settle = settlement_byma(date.today().strftime("%Y-%m-%d"), lag=1).date()
        target_date = _cer_reference_date(settle, inst.cer_lag)
        cer_val = indices_provider.get_cer(target_date)
        if not (cer_val and inst.cer_base):
            return 100.0

        # Residual nominal after past amortizations (matters only for amortizing bonds).
        amortized = sum(cf.amortization for cf in inst.cashflows if cf.date < settle)
        residual = max(100.0 - amortized, 0.0)
        return residual * cer_val / inst.cer_base

    @staticmethod
    def calculate_tir(
        snapshot: MarketSnapshot,
        indices_provider=None,
        fx_provider=None,
    ) -> Optional[float]:
        """Internal Rate of Return (TIR) as a decimal fraction (0.30 = 30%).

        For CER-indexed bonds, computes the REAL TIR per BCRA Nota Técnica
        N°8/2024 Eq. A7: price is deflated by CER_LIQ-10h / CER_BASE and IRR
        is solved against the nominal-base cashflows (per-100 nominal).

        For DOLAR_LINKED bonds, computes the USD TIR: price is deflated by
        the mayorista venta rate (pesos/USD) to express today's investment in
        USD, then solved against USD-100 payback at maturity.

        Requires Excel `Cashflows` to be stored in base terms — see agents.md.
        """
        inst = snapshot.instrument
        if not inst or not snapshot.price:
            return None

        settle_date = _settlement_for(inst.instrument_type)

        # TAMAR PURO: bond accrues at daily TAMAR rate from emission to maturity.
        # Expected payback = 100 * accrued_so_far * (1 + TAMAR_today/365)^days_remaining.
        if _is_tamar_puro_type(inst.instrument_type) and indices_provider \
                and inst.emission_date and inst.maturity_date and inst.maturity_date > settle_date:
            accrued = _accrued_tamar_factor(inst.emission_date, settle_date, indices_provider)
            tamar_today_pct = indices_provider.get_tamar()
            df_today = _tamar_daily_factor(tamar_today_pct)
            if accrued is None or df_today is None:
                return None
            days_remaining = (inst.maturity_date - settle_date).days
            expected_payback = 100.0 * accrued * (df_today ** days_remaining)
            flows = [-snapshot.price, expected_payback]
            dates = [settle_date, inst.maturity_date]
            tir = FinancialEngine.xirr(flows, dates)
            return float(tir) if not np.isnan(tir) else None

        # DUAL TAMAR: daily payoff = max(TAMAR_daily, fixed_daily_from_TEM).
        if _is_dual_tamar_type(inst.instrument_type) and indices_provider \
                and inst.emission_date and inst.maturity_date and inst.maturity_date > settle_date \
                and inst.floor_rate_monthly is not None:
            accrued = _accrued_dual_factor(inst.emission_date, settle_date,
                                           inst.floor_rate_monthly, indices_provider)
            tamar_today_pct = indices_provider.get_tamar()
            tamar_df = _tamar_daily_factor(tamar_today_pct) or 1.0
            fixed_df = _fixed_daily_factor_from_monthly(inst.floor_rate_monthly) or 1.0
            fwd_df = max(tamar_df, fixed_df)
            if accrued is None:
                return None
            days_remaining = (inst.maturity_date - settle_date).days
            expected_payback = 100.0 * accrued * (fwd_df ** days_remaining)
            flows = [-snapshot.price, expected_payback]
            dates = [settle_date, inst.maturity_date]
            tir = FinancialEngine.xirr(flows, dates)
            return float(tir) if not np.isnan(tir) else None

        # USD TIR for DOLAR LINKED bonds
        if _is_dolar_linked_type(inst.instrument_type) and fx_provider:
            fx = fx_provider.get_mayorista_venta()
            if fx and fx > 0 and inst.maturity_date and inst.maturity_date > settle_date:
                real_price_usd = snapshot.price / fx
                flows = [-real_price_usd, 100.0]
                dates = [settle_date, inst.maturity_date]
                tir = FinancialEngine.xirr(flows, dates)
                return float(tir) if not np.isnan(tir) else None
            return None

        future_cfs = inst.get_future_cashflows(settle_date)
        if not future_cfs:
            return None

        # Real TIR for CER bonds: deflate price by CER ratio.
        if _is_cer_type(inst.instrument_type) and indices_provider and inst.cer_base:
            target_s = _cer_reference_date(settle_date, inst.cer_lag)
            cer_s = indices_provider.get_cer(target_s)
            if cer_s:
                real_price = snapshot.price / (cer_s / inst.cer_base)
                flows = [-real_price] + [cf.total for cf in future_cfs]
                dates = [settle_date] + [cf.date for cf in future_cfs]
                tir = FinancialEngine.xirr(flows, dates)
                return float(tir) if not np.isnan(tir) else None

        flows = [-snapshot.price] + [cf.total for cf in future_cfs]
        dates = [settle_date] + [cf.date for cf in future_cfs]
        tir = FinancialEngine.xirr(flows, dates)
        return float(tir) if not np.isnan(tir) else None

    @staticmethod
    def calculate_duration(snapshot: MarketSnapshot, tir: float) -> Optional[float]:
        inst = snapshot.instrument
        if not inst or tir is None or np.isnan(tir):
            return None

        lag = 0 if "LECER" in inst.instrument_type else 1
        settle_date = settlement_byma(date.today().strftime("%Y-%m-%d"), lag=lag).date()

        # Bullet bonds (single payment at maturity): DL, TAMAR PURO, DUAL TAMAR.
        is_bullet = (
            _is_dolar_linked_type(inst.instrument_type)
            or _is_tamar_puro_type(inst.instrument_type)
            or _is_dual_tamar_type(inst.instrument_type)
        )
        if is_bullet and inst.maturity_date and inst.maturity_date > settle_date:
            years = (inst.maturity_date - settle_date).days / 365.25
            return years / (1 + tir)

        future_cfs = inst.get_future_cashflows(settle_date)
        if not future_cfs:
            return None

        total_pv = 0.0
        weighted_pv = 0.0
        for cf in future_cfs:
            t = (cf.date - settle_date).days / 365.25
            pv = cf.total / (1 + tir) ** t
            total_pv += pv
            weighted_pv += pv * t

        if total_pv == 0:
            return 0.0
        macaulay = weighted_pv / total_pv
        return macaulay / (1 + tir)

    @staticmethod
    def calculate_theoretical_price(
        instrument, tir: float, reference_date: date
    ) -> Optional[float]:
        """Price implied by discounting future cashflows at the given TIR (decimal fraction)."""
        if instrument is None or tir is None:
            return None
        future = instrument.get_future_cashflows(reference_date)
        if not future:
            return None
        price = 0.0
        for cf in future:
            years = (cf.date - reference_date).days / 365.25
            if years <= 0:
                continue
            price += cf.total / (1 + tir) ** years
        return price if price > 0 else None

    @staticmethod
    def calculate_pct_change(
        current: Optional[float], previous: Optional[float]
    ) -> Optional[float]:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / previous
