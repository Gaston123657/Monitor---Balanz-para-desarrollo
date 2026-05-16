"""Yield curve modelling and Break-Even Inflation.

Implements:
- Nelson-Siegel parametric curve (BCRA Nota Técnica N°8/2024, Eq. 11)
- Fisher parity for break-even inflation (Eq. 8)
- Lag-adjusted forward BEI using the gamma factor (Eq. A4 / A10)

Conventions:
- Tenors are in years.
- Rates are decimal fractions (0.30 = 30% annual).
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class NelsonSiegelCurve:
    """Nelson-Siegel curve: i(T) = β₀ + β₁·d(γT) + β₂·(d(γT) - e^(-γT))

    where d(x) = (1 - e^(-x)) / x. β₀ is the long-term level, β₁ the short-term
    slope, β₂ the medium-term curvature, γ the decay rate.
    """

    beta0: float
    beta1: float
    beta2: float
    gamma: float

    def __call__(self, t: float) -> float:
        if t <= 0:
            return self.beta0 + self.beta1
        gT = self.gamma * t
        decay = (1.0 - np.exp(-gT)) / gT
        return self.beta0 + self.beta1 * decay + self.beta2 * (decay - np.exp(-gT))

    @classmethod
    def fit(cls, tenors: Sequence[float], yields: Sequence[float]) -> "NelsonSiegelCurve":
        """Calibrate β₀,β₁,β₂,γ via non-linear least squares on observed points."""
        tenors_arr = np.asarray(tenors, dtype=float)
        yields_arr = np.asarray(yields, dtype=float)
        if tenors_arr.size < 3:
            raise ValueError("Need at least 3 (tenor, yield) points to fit Nelson-Siegel.")

        def residuals(params):
            b0, b1, b2, g = params
            gT = g * tenors_arr
            decay = (1.0 - np.exp(-gT)) / gT
            model = b0 + b1 * decay + b2 * (decay - np.exp(-gT))
            return model - yields_arr

        x0 = [float(yields_arr.mean()), 0.0, 0.0, 1.0]
        bounds = ([-1.0, -2.0, -2.0, 1e-3], [3.0, 2.0, 2.0, 50.0])
        result = least_squares(residuals, x0, bounds=bounds, max_nfev=2000)
        return cls(float(result.x[0]), float(result.x[1]), float(result.x[2]), float(result.x[3]))


def fisher_break_even(nominal_rate: float, real_rate: float) -> float:
    """π = (1+i)/(1+r) - 1, per BCRA TN 8/2024 Eq. 8."""
    return (1.0 + nominal_rate) / (1.0 + real_rate) - 1.0


def gamma_known_cer_factor(
    cer_at_liq_minus_10h: Optional[float],
    cer_last_published: Optional[float],
) -> Optional[float]:
    """γ = CER_ULT_CONOCIDO / CER_LIQ-10h, per BCRA TN 8/2024 Eq. A4.

    Represents the already-known portion of CER variation between the
    liquidation-lagged reference and the most recent published value.
    """
    if not cer_at_liq_minus_10h or not cer_last_published or cer_at_liq_minus_10h <= 0:
        return None
    return cer_last_published / cer_at_liq_minus_10h


def forward_bei(
    nominal_rate: float,
    real_rate: float,
    gamma: Optional[float] = None,
) -> float:
    """Forward inflation expectation, optionally stripping known CER variation.

    Without gamma:  π = (1+i)/(1+r) - 1                 (spot BEI)
    With gamma:     π = (1+i)/((1+r)·γ) - 1             (forward, lag-adjusted)
    """
    raw = (1.0 + nominal_rate) / (1.0 + real_rate)
    if gamma and gamma > 0:
        raw = raw / gamma
    return raw - 1.0
