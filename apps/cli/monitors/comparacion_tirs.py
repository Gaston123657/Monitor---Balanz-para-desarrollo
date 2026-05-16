import logging
from datetime import datetime

import numpy as np
import pandas as pd

from apps.cli.monitors._common import (
    build_use_case,
    fmt_num,
    fmt_tir,
    save_report,
)
from core.domain.instrument_groups import SOBERANOS
from core.domain.services import FinancialEngine

logger = logging.getLogger(__name__)


def generate_comparacion_report(output_dir: str):
    logger.info("Generando reporte de COMPARACIÓN DE TIRs...")
    use_case = build_use_case()
    metrics_list = use_case.execute(SOBERANOS)
    if not metrics_list:
        return None

    tirs = [m.tir for m in metrics_list if m.tir is not None]
    # TIR is a decimal fraction (0.30 = 30%); convert to percentage units for the scenario center.
    avg_tir_pct = (np.mean(tirs) if tirs else 0.30) * 100.0
    center = int(round(avg_tir_pct))
    scenarios_pct = [center + delta for delta in (-2, -1, 0, 1, 2)]
    ref_date = datetime.now().date()

    rows = []
    for m in metrics_list:
        row = {
            "Ticker": m.snapshot.instrument.ticker,
            "Precio": fmt_num(m.snapshot.price) if m.snapshot.price else "-",
            "TIR": fmt_tir(m.tir),
            "DM": fmt_num(m.duration),
        }

        for s_pct in scenarios_pct:
            px_theo = FinancialEngine.calculate_theoretical_price(
                m.snapshot.instrument, s_pct / 100.0, ref_date
            )
            if px_theo and m.snapshot.price:
                pct = (px_theo - m.snapshot.price) / m.snapshot.price * 100.0
                row[f"{s_pct}%"] = f"{pct:+.2f}%"
            else:
                row[f"{s_pct}%"] = "-"

        rows.append(row)

    df = pd.DataFrame(rows)
    return save_report(df, output_dir, "monitor_comparacion", "COMPARACION DE TIR'S - ESCENARIOS DE SENSIBILIDAD")
