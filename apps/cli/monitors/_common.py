"""Shared helpers for CLI monitors: bootstrap pipeline, formatters, save report."""
import logging
import os
from datetime import datetime, date
from typing import Callable, Iterable, Optional

import pandas as pd

from config.settings import MASTER_XLSX
from core.domain.models import InstrumentMetrics
from core.infrastructure.repositories import (
    Data912MarketDataProvider,
    ExcelInstrumentsRepository,
)
from core.use_cases.generate_report import GenerateMonitorReport
from presentation.console_printer import print_monitor
from presentation.png_exporter import draw_monitor_png

logger = logging.getLogger(__name__)

DASH = "-"

_REPO_CACHE: dict[str, ExcelInstrumentsRepository] = {}


def get_repository(path: str = MASTER_XLSX) -> ExcelInstrumentsRepository:
    if path not in _REPO_CACHE:
        _REPO_CACHE[path] = ExcelInstrumentsRepository(path)
    return _REPO_CACHE[path]


def build_use_case() -> GenerateMonitorReport:
    return GenerateMonitorReport(get_repository(), Data912MarketDataProvider())


def fmt_num(v: Optional[float], decimals: int = 2) -> str:
    return f"{v:.{decimals}f}" if v is not None else DASH


def fmt_pct(v: Optional[float], decimals: int = 2, scale: float = 1.0) -> str:
    if v is None:
        return DASH
    return f"{v * scale:.{decimals}f}%"


def fmt_signed_pct(v: Optional[float], decimals: int = 2, scale: float = 1.0) -> str:
    if v is None:
        return DASH
    return f"{v * scale:+.{decimals}f}%"


def fmt_tir(v: Optional[float]) -> str:
    # TIR comes back as a decimal fraction (0.30 = 30%); display as percentage.
    return fmt_pct(v, decimals=2, scale=100.0)


def fmt_date(d, fmt: str = "%d/%m/%y") -> str:
    return d.strftime(fmt) if d else DASH


def fmt_volume(v: Optional[float]) -> str:
    """Compact ARS volume: 14.4B, 456.7M, 12K."""
    if v is None or v == 0:
        return DASH
    if v >= 1e9:
        return f"{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}"


def last_future_cashflow_date(metrics: InstrumentMetrics, reference: Optional[date] = None):
    inst = metrics.snapshot.instrument
    if inst is None or not inst.cashflows:
        return None
    ref = reference or datetime.now().date()
    future = inst.get_future_cashflows(ref)
    return future[-1].date if future else None


def save_report(df: pd.DataFrame, output_dir: str, prefix: str, title: str) -> str:
    print_monitor(title, df)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = os.path.join(output_dir, f"{prefix}_{timestamp}.png")
    draw_monitor_png(df, png_path, title)
    return png_path


def run_monitor(
    types: Iterable[str],
    title: str,
    prefix: str,
    output_dir: str,
    row_builder: Callable[[InstrumentMetrics], dict],
    sort_by: Optional[str] = None,
    log_label: Optional[str] = None,
) -> Optional[str]:
    label = log_label or title
    logger.info(f"Generando reporte de {label}...")

    use_case = build_use_case()
    metrics_list = use_case.execute(list(types))

    if not metrics_list:
        logger.error(f"No se obtuvieron métricas para {label}.")
        return None

    df = pd.DataFrame([row_builder(m) for m in metrics_list])
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by)

    return save_report(df, output_dir, prefix, title)
