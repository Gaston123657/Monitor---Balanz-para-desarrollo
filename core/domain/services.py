import logging
from datetime import date, timedelta
from typing import List, Optional

import numpy as np
from scipy.optimize import brentq, newton

from core.domain.models import MarketSnapshot
from core.holiday_engine import is_habil, settlement_byma

logger = logging.getLogger(__name__)


def _is_cer_type(instrument_type: str) -> bool:
    # "LECER" already contains "CER", so a single substring check is enough.
    return "CER" in instrument_type


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
    def calculate_tir(snapshot: MarketSnapshot, indices_provider=None) -> Optional[float]:
        """Internal Rate of Return (TIR) as a decimal fraction (0.30 = 30%).

        For CER-indexed bonds, computes the REAL TIR per BCRA Nota Técnica
        N°8/2024 Eq. A7: price is deflated by CER_LIQ-10h / CER_BASE and IRR
        is solved against the nominal-base cashflows (per-100 nominal).
        Requires Excel `Cashflows` to be stored in base terms — see agents.md.
        """
        inst = snapshot.instrument
        if not inst or not snapshot.price:
            return None

        settle_date = _settlement_for(inst.instrument_type)
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
