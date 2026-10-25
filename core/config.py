"""Application configuration resolved from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_PORT = 8000
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///app.db"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_BOT_USERNAME = ""


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for the service."""

    bot_token: str
    bot_username: str
    port: int
    database_url: str
    log_level: str


def load_settings() -> Settings:
    """Read settings from the environment.

    Raises:
        RuntimeError: If PORT is set to a non-integer value.
    """
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        raise RuntimeError(
            f"Invalid PORT value {raw_port!r}: expected an integer"
        ) from None

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        bot_username=os.getenv("BOT_USERNAME", DEFAULT_BOT_USERNAME)
        .strip()
        .lstrip("@"),
        port=port,
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
    )


settings = load_settings()
