import os
from pathlib import Path
from dotenv import load_dotenv

# BASE DIR
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Instagram Credentials (다중 계정 콤마 구분 지원)
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID", "")
INSTAGRAM_SESSION_ID_2 = os.getenv("INSTAGRAM_SESSION_ID_2", "")

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# App Settings
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "15"))  # 초단위 감시 주기 (15초 클라우드 안전 주기)

DB_PATH = BASE_DIR / "messages.db"
SESSION_PATH = BASE_DIR / "session.json"
