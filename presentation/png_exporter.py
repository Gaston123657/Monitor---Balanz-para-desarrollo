import os
import logging
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

from config.theme import (
    COLORS, TABLE_BBOX, TITLE_Y, SUBTITLE_Y, 
    FONTSIZE_TITLE, FONTSIZE_SUBTITLE, FONTSIZE_TABLE, TABLE_ROW_HEIGHT,
    MONITOR_FIGSIZE, MONITOR_DPI
)

logger = logging.getLogger(__name__)

def draw_monitor_png(df, output_path, title):
    """Dibuja una tabla como imagen PNG genérica."""
    fig = plt.figure(figsize=MONITOR_FIGSIZE, dpi=MONITOR_DPI)
    fig.patch.set_facecolor(COLORS["bg_dark"])

    ax = fig.add_axes([0.03, 0.05, 0.94, 0.9])
    ax.set_facecolor(COLORS["bg_dark"])
    ax.axis("off")

    # Títulos
    ax.text(
        0.5, TITLE_Y, title,
        ha="center", va="center",
        color=COLORS["text_white"], fontsize=FONTSIZE_TITLE, fontweight="bold",
        transform=ax.transAxes
    )
    subtitle = f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    ax.text(
        0.5, SUBTITLE_Y, subtitle,
        ha="center", va="center",
        color=COLORS["text_subtitle"], fontsize=FONTSIZE_SUBTITLE,
        transform=ax.transAxes
    )

    # Tabla
    tbl = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        cellLoc="center",
        colLoc="center",
        bbox=TABLE_BBOX
    )

    tbl.auto_set_font_size(False)
    tbl.set_fontsize(FONTSIZE_TABLE)
    tbl.scale(1, TABLE_ROW_HEIGHT)

    # Estilo de celdas
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor(COLORS["border"])
        if row == 0:  # Header
            cell.set_facecolor(COLORS["bg_table_header"])
            cell.set_text_props(color=COLORS["text_white"], weight="bold")
        else:  # Data rows
            cell.set_facecolor(COLORS["bg_table_alt1"] if row % 2 == 0 else COLORS["bg_table_alt2"])
            cell.set_text_props(color=COLORS["text_light"])

    # Colorear variaciones porcentuales (detecta si el string tiene un % y es negativo/positivo)
    for r in range(len(df)):
        for c in range(len(df.columns)):
            val = str(df.iloc[r, c]).strip()
            # Si es una columna de variación porcentual o termina en '%'
            if "%" in val:
                try:
                    num_val = float(val.replace("%", "").replace(",", "."))
                    cell = tbl[(r + 1, c)]
                    if num_val > 0:
                        cell.set_text_props(color=COLORS["text_positive"], weight="bold")
                    elif num_val < 0:
                        cell.set_text_props(color=COLORS["text_negative"], weight="bold")
                except ValueError:
                    pass

    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    logger.info(f"PNG guardado: {output_path}")
