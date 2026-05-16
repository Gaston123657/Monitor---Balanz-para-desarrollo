from apps.cli.monitors._common import (
    fmt_num,
    fmt_pct,
    fmt_tir,
    fmt_volume,
    run_monitor,
)
from core.domain.instrument_groups import SOBERANOS


def _row(m):
    s = m.snapshot
    return {
        "Ticker": s.instrument.ticker,
        "Precio": fmt_num(s.price) if s.price else "-",
        "TIR": fmt_tir(m.tir),
        "Var 1D": fmt_pct(s.change_pct),
        "Var 7D": fmt_pct(m.variance_7d, scale=100.0),
        "Var 30D": fmt_pct(m.variance_30d, scale=100.0),
        "Var 1Y": fmt_pct(m.variance_1y, scale=100.0),
        "Bid": fmt_num(s.bid),
        "Ask": fmt_num(s.ask),
        "Vol $": fmt_volume(s.volume),
    }


def generate_bonares_report(output_dir: str):
    return run_monitor(
        types=SOBERANOS,
        title="MONITOR BONOS SOBERANOS ARGENTINA - AL / GD",
        prefix="monitor_bonos",
        output_dir=output_dir,
        row_builder=_row,
        log_label="BONARES/GLOBALES",
    )
