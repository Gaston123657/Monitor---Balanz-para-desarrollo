"""Tests del sintético de tasa en pesos (dólar-linked + short dólar futuro).

Cubre `core.domain.dlr_synthetics.build_dl_synthetic_rows`: la fórmula
TEA = (100·F / P_dl)^(365/d) − 1, la identidad de descomposición
(1+sint) = (1+tir_dl)·(1+tea_fut), el calce con el futuro más cercano y los
filtros (sin precio / sin vto / vencido / sin futuro dentro del gap)."""

from datetime import date

import pytest

from core.domain.dlr_synthetics import build_dl_synthetic_rows


TODAY = date(2026, 6, 18)
SPOT = 1200.0
SYMBOLS = ["DLR/AGO26", "DLR/DIC26"]
QUOTES = {
    "DLR/AGO26": {"last": 1290.0},
    "DLR/DIC26": {"last": 1450.0},
}
# Curva de pesos dummy: TEA fija constante 45% + dos instrumentos de referencia.
PESO_CURVE = {
    "curve": lambda y: 0.45,
    "t_range": (0.1, 2.0),
    "instruments": [(0.2, "S31L6", 0.48), (0.55, "T15D6", 0.42)],
}


def _row(price=99.0 * SPOT, maturity=date(2026, 8, 31), ticker="TZVD6"):
    specs = [{"ticker": ticker, "maturity": maturity, "price": price}]
    rows = build_dl_synthetic_rows(specs, QUOTES, SYMBOLS, SPOT, TODAY, PESO_CURVE)
    return rows


def test_synthetic_tea_matches_closed_form():
    rows = _row()
    assert len(rows) == 1
    r = rows[0]
    F, P, d = 1290.0, 99.0 * SPOT, (date(2026, 8, 31) - TODAY).days
    expected = (100.0 * F / P) ** (365.0 / d) - 1.0
    assert r["tea_sint"] == pytest.approx(expected, rel=1e-9)
    assert r["dias"] == d


def test_spot_cancels_out():
    """La tasa sintética NO depende del spot (se cancela algebraicamente)."""
    base = _row()[0]["tea_sint"]
    specs = [{"ticker": "TZVD6", "maturity": date(2026, 8, 31), "price": 99.0 * SPOT}]
    other = build_dl_synthetic_rows(specs, QUOTES, SYMBOLS, 999.0, TODAY, PESO_CURVE)
    assert other[0]["tea_sint"] == pytest.approx(base, rel=1e-12)


def test_decomposition_identity():
    """(1 + sintético) = (1 + tir_dl_USD) · (1 + tea_futuro)."""
    r = _row()[0]
    lhs = 1.0 + r["tea_sint"]
    rhs = (1.0 + r["tir_dl"]) * (1.0 + r["tea_fut"])
    assert lhs == pytest.approx(rhs, rel=1e-9)


def test_nearest_future_pairing_and_gap():
    """El DL se calza con el futuro de vto más cercano; gap=0 si coincide mes."""
    r = _row(maturity=date(2026, 8, 31))[0]
    assert r["fut_ticker"] == "DLR/AGO26"
    assert r["gap_dias"] == 0


def test_spread_vs_fija():
    r = _row()[0]
    assert r["tea_fija"] == pytest.approx(0.45)
    assert r["spread"] == pytest.approx(r["tea_sint"] - 0.45, rel=1e-9)
    assert r["inst_ticker"] == "S31L6"
    assert r["spread_inst"] == pytest.approx(r["tea_sint"] - 0.48, rel=1e-9)


def test_skips_without_price_or_maturity():
    specs = [
        {"ticker": "A", "maturity": date(2026, 8, 31), "price": None},
        {"ticker": "B", "maturity": None, "price": 100000.0},
        {"ticker": "C", "maturity": date(2026, 8, 31), "price": 0.0},
    ]
    assert build_dl_synthetic_rows(specs, QUOTES, SYMBOLS, SPOT, TODAY, PESO_CURVE) == []


def test_skips_matured_dl():
    rows = _row(maturity=date(2026, 6, 1))  # ya vencido
    assert rows == []


def test_skips_when_no_future_within_gap():
    """Sin futuro cercano (gap > max_gap_days) no hay sintético."""
    specs = [{"ticker": "TZXD8", "maturity": date(2028, 6, 30), "price": 95.0 * SPOT}]
    rows = build_dl_synthetic_rows(
        specs, QUOTES, SYMBOLS, SPOT, TODAY, PESO_CURVE, max_gap_days=45
    )
    assert rows == []


def test_no_curve_still_computes_synthetic():
    """Sin curva de pesos, la tasa sintética se calcula igual (spread = None)."""
    specs = [{"ticker": "TZVD6", "maturity": date(2026, 8, 31), "price": 99.0 * SPOT}]
    rows = build_dl_synthetic_rows(specs, QUOTES, SYMBOLS, SPOT, TODAY, None)
    assert len(rows) == 1
    assert rows[0]["tea_sint"] is not None
    assert rows[0]["spread"] is None
    assert rows[0]["inst_ticker"] is None
