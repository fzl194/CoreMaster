# backend/core/config.py
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLUGINS_DIR = BASE_DIR / "plugins"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "coremaster.db"
