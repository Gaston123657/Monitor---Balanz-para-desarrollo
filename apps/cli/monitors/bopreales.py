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
    return {
        "Ticker": s.instrument.ticker,
        "Vencimiento": fmt_date(vto, "%b-%y").lower() if vto else "-",
        "Precio": fmt_num(s.price) if s.price else "-",
        "TIR": fmt_tir(m.tir),
        "DM": fmt_num(m.duration),
        "Var 1D": fmt_pct(s.change_pct),
        "Var 7D": fmt_pct(m.variance_7d, scale=100.0),
        "Var 30D": fmt_pct(m.variance_30d, scale=100.0),
        "Bid": fmt_num(s.bid),
        "Ask": fmt_num(s.ask),
    }


def generate_bopreales_report(output_dir: str):
    return run_monitor(
        types=["BOPREAL"],
        title="MONITOR BONOS BOPREALES",
        prefix="monitor_bopreales",
        output_dir=output_dir,
        row_builder=_row,
        log_label="BOPREALES",
    )
