import logging
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

def print_monitor(title, combined_df):
    """
    Imprime un dataframe de forma estilizada en consola.
    """
    if combined_df is None or combined_df.empty:
        logger.warning(f"No hay datos para mostrar en {title}.")
        return

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("\n" + "=" * 100)
    print(f"{title} - Actualizado: {timestamp}")
    print("=" * 100)
    print(combined_df.to_string(index=False))
    print("=" * 100 + "\n")
