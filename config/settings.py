import os
import logging

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv():
    """Tiny .env loader. KEY=VALUE per line, # for comments. Skips existing env vars."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


_load_dotenv()
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
