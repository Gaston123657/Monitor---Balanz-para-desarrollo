from apps.cli.monitors._common import (
    fmt_date,
    fmt_num,
    fmt_pct,
    fmt_tir,
    fmt_volume,
    last_future_cashflow_date,
    run_monitor,
)
from core.domain.instrument_groups import CER


def _row(m):
    s = m.snapshot
    vto = last_future_cashflow_date(m)
    return {
        "Ticker": s.instrument.ticker,
        "Categoría": s.instrument.category or "-",
        "Tipo": s.instrument.instrument_type,
        "Precio": fmt_num(s.price) if s.price else "-",
        "TIR": fmt_tir(m.tir),
        "Var 1D": fmt_pct(s.change_pct),
        "Var 7D": fmt_pct(m.variance_7d, scale=100.0),
        "Var 30D": fmt_pct(m.variance_30d, scale=100.0),
        "Dur.Mod": fmt_num(m.duration),
        "Vto": fmt_date(vto),
        "Vol $": fmt_volume(s.volume),
    }


def generate_cer_report(output_dir: str):
    return run_monitor(
        types=CER,
        title="MONITOR BONOS CER - INFLACIÓN",
        prefix="monitor_cer",
        output_dir=output_dir,
        row_builder=_row,
        log_label="BONOS CER",
    )
