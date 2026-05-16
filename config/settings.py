import os
import logging

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MASTER_XLSX = os.path.join(DATA_DIR, "instruments_master.xlsx")

# Constantes de negocio
REFRESH_INTERVAL_SEC = 30
HISTORY_DAYS = 120
PRICE_SCALE_THRESHOLD = 1000

# Logging centralizado
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logging():
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("monitores_global.log", encoding="utf-8")
        ]
    )
