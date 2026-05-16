from datetime import datetime

from apps.cli.monitors._common import (
    fmt_date,
    fmt_num,
    fmt_pct,
    fmt_tir,
    last_future_cashflow_date,
    run_monitor,
)


def _row(m):
    s = m.snapshot
    vto = last_future_cashflow_date(m)
    dias = (vto - datetime.now().date()).days if vto else 0
    return {
        "Ticker": s.instrument.ticker,
        "Días": dias,
        "Precio": fmt_num(s.price) if s.price else "-",
        "TEA%": fmt_tir(m.tir),
        "Var 1D": fmt_pct(s.change_pct),
        "Var 7D": fmt_pct(m.variance_7d, scale=100.0),
        "DM": fmt_num(m.duration),
        "Vto": fmt_date(vto),
    }


def generate_tasa_fija_report(output_dir: str):
    return run_monitor(
        types=["LECAP", "BONCAP", "DUAL", "BONOFIJA"],
        title="MONITOR LETRAS Y BONCAPS — TASA FIJA",
        prefix="monitor_tasa_fija",
        output_dir=output_dir,
        row_builder=_row,
        sort_by="Días",
        log_label="TASA FIJA",
    )
