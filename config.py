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
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID", "")

# Telegram Bot Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# App Settings
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3"))  # 초단위 감시 주기 (3초 초고속 감지)

DB_PATH = BASE_DIR / "messages.db"
SESSION_PATH = BASE_DIR / "session.json"
