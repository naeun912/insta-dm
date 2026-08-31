import os
from pathlib import Path
from dotenv import load_dotenv

# BASE DIR
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Instagram Credentials
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# App Settings
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "12"))  # 초 단위 감시 주기 (기본 12초)
DB_PATH = BASE_DIR / "messages.db"
SESSION_PATH = BASE_DIR / "session.json"
