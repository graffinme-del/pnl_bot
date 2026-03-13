from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_env()


@dataclass(frozen=True)
class Settings:
    binance_api_key: str
    binance_api_secret: str
    telegram_bot_token: str
    timezone: ZoneInfo
    report_chat_id: int


def get_settings() -> Settings:
    tz_name = os.getenv("TIMEZONE", "Europe/Moscow")
    timezone = ZoneInfo(tz_name)

    return Settings(
        binance_api_key=os.environ["BINANCE_API_KEY"],
        binance_api_secret=os.environ["BINANCE_API_SECRET"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        timezone=timezone,
        report_chat_id=int(os.environ["REPORT_CHAT_ID"]),
    )


SETTINGS = get_settings()

