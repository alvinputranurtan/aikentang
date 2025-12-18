import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class AppConfig:
    # DB
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_NAME: str = os.getenv("DB_NAME", "")
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASS: str = os.getenv("DB_PASS", "")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DEVICE_ID: int = int(os.getenv("DEVICE_ID", "3"))

    # Model
    PATH_MODEL_1: str = os.getenv("PATH_MODEL_1", "model_1.pt")
    PATH_MODEL_2: str = os.getenv("PATH_MODEL_2", "model_2.pt")
    MODEL_AGE_SWITCH_DAYS: int = int(os.getenv("MODEL_AGE_SWITCH_DAYS", "15"))

    # Detection
    DEAD_CLASS_NAME: str = os.getenv("DEAD_CLASS_NAME", "dead")
    DEAD_CONF: float = float(os.getenv("DEAD_CONF", "0.35"))
    DEAD_HITS_REQUIRED: int = int(os.getenv("DEAD_HITS_REQUIRED", "30"))
    RECOVER_AFTER_SEC: int = int(os.getenv("RECOVER_AFTER_SEC", "30"))
    DB_COOLDOWN_SEC: int = int(os.getenv("DB_COOLDOWN_SEC", "5"))

    # Telegram
    TG_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TG_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    TG_COOLDOWN_SEC: int = int(os.getenv("TELEGRAM_COOLDOWN_SEC", "10"))

    def telegram_enabled(self) -> bool:
        return bool(self.TG_BOT_TOKEN) and bool(self.TG_CHAT_ID)
