"""Tests del store histórico — round-trip append/read + idempotencia del upsert."""

import pytest

from core.infrastructure import history_store


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Apunta el store a un dir temporal y limpia el cache entre tests."""
    monkeypatch.setattr(history_store, "HISTORY_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    history_store._cache.clear()
    yield
    history_store._cache.clear()


def _row(ticker, panel="bonares", price=100.0, tir=0.10, duration=2.0):
    return {
        "ticker": ticker, "panel": panel, "price": price, "technical_value": 98.0,
        "parity": 1.02, "tir": tir, "tna": 0.095, "tem": 0.008,
        "tna_360": 0.094, "tem_360": 0.0079, "duration": duration,
        "change_pct": -0.5, "volume": 1_000_000.0,
    }


def test_append_and_read_series_round_trip():
    history_store.append_snapshot("2026-06-10", [_row("AL30D", price=63.0, tir=0.11)])
    history_store.append_snapshot("2026-06-11", [_row("AL30D", price=64.0, tir=0.10)])

    serie = history_store.read_series("AL30D", "price")
    assert serie == [
        {"fecha": "2026-06-10", "valor": 63.0},
        {"fecha": "2026-06-11", "valor": 64.0},
    ]


def test_read_curve_groups_by_date_and_sorts_by_md():
    rows = [
        _row("AL30D", duration=3.0, tir=0.11),
        _row("AL35D", duration=1.0, tir=0.09),
        _row("T2X5", panel="cer", duration=2.0, tir=0.05),  # otro panel: se excluye
    ]
    history_store.append_snapshot("2026-06-12", rows)

    curve = history_store.read_curve("bonares", ["2026-06-12"])
    pts = curve["2026-06-12"]
    assert [p["ticker"] for p in pts] == ["AL35D", "AL30D"]  # ordenado por md asc
    assert pts[0]["md"] == 1.0 and pts[1]["md"] == 3.0


def test_append_is_idempotent_last_write_wins():
    history_store.append_snapshot("2026-06-12", [_row("AL30D", price=63.0)])
    # Reescribir el mismo día/ticker: el último valor gana (cierre).
    history_store.append_snapshot("2026-06-12", [_row("AL30D", price=63.9)])

    serie = history_store.read_series("AL30D", "price")
    assert serie == [{"fecha": "2026-06-12", "valor": 63.9}]


def test_read_curve_skips_rows_without_md_or_tir():
    rows = [_row("AL30D", duration=2.0, tir=0.11), _row("AL35D")]
    rows[1]["duration"] = None  # sin MD → no se puede ubicar en la curva
    history_store.append_snapshot("2026-06-12", rows)

    pts = history_store.read_curve("bonares", ["2026-06-12"])["2026-06-12"]
    assert [p["ticker"] for p in pts] == ["AL30D"]


def test_append_merges_other_tickers_same_date():
    # Simula live + backfill: dos appends del mismo día con tickers distintos
    # NO deben pisarse (upsert por (fecha,ticker), no replace-whole-day).
    history_store.append_snapshot("2026-06-12", [_row("AL30D")], source="live")
    history_store.append_snapshot("2026-06-12", [_row("GD30D")], source="lseg_backfill")
    tickers = history_store.available_tickers()
    assert tickers == ["AL30D", "GD30D"]


def test_read_series_rejects_invalid_metric():
    history_store.append_snapshot("2026-06-12", [_row("AL30D")])
    with pytest.raises(ValueError):
        history_store.read_series("AL30D", "nonexistent")


def test_available_dates_and_tickers():
    history_store.append_snapshot("2026-06-10", [_row("AL30D")])
    history_store.append_snapshot("2026-07-01", [_row("AL35D")])
    assert history_store.available_dates() == ["2026-06-10", "2026-07-01"]
    assert history_store.available_tickers() == ["AL30D", "AL35D"]
