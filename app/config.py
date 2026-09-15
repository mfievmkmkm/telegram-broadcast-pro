import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _ids(value: str) -> set[int]:
    result = set()
    for item in (value or "").split(","):
        item = item.strip()
        if item and item.lstrip("-").isdigit():
            result.add(int(item))
    return result


def _db_url(value: str) -> str:
    value = (value or "").strip() or "sqlite+aiosqlite:///data/bot.db"
    if value.startswith("postgres://"):
        return "postgresql+asyncpg://" + value[len("postgres://"):]
    if value.startswith("postgresql://") and "+asyncpg" not in value:
        return "postgresql+asyncpg://" + value[len("postgresql://"):]
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    owner_ids: set[int] = frozenset(_ids(os.getenv("OWNER_IDS", "")))
    database_url: str = _db_url(os.getenv("DATABASE_URL", ""))
    api_id: int = int(os.getenv("API_ID", "0") or 0)
    api_hash: str = os.getenv("API_HASH", "").strip()
    session_secret: str = os.getenv("SESSION_SECRET", "").strip()
    timezone: str = os.getenv("TIMEZONE", "Asia/Yekaterinburg").strip()
    send_delay_seconds: float = float(os.getenv("SEND_DELAY_SECONDS", "2.0"))
    worker_poll_seconds: int = int(os.getenv("WORKER_POLL_SECONDS", "5"))
    max_accounts_per_user: int = int(os.getenv("MAX_ACCOUNTS_PER_USER", "5"))
    max_targets_per_campaign: int = int(os.getenv("MAX_TARGETS_PER_CAMPAIGN", "100"))
    min_repeat_minutes: int = int(os.getenv("MIN_REPEAT_MINUTES", "15"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()
