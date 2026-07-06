"""
bot/config.py
Loads environment variables from .env and exposes a typed Config dataclass.
Import the singleton `config` object — never access os.environ directly elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Typed configuration loaded from environment variables."""

    bot_token: str
    guild_ids: list[int] = field(default_factory=list)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config instance from environment variables. Raises if required values are missing."""
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN is not set. Copy .env.example to .env and fill in your token.")

        raw_guild_ids = os.getenv("GUILD_IDS", "")
        guild_ids = [int(g.strip()) for g in raw_guild_ids.split(",") if g.strip().isdigit()]

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        return cls(bot_token=token, guild_ids=guild_ids, log_level=log_level)


# Singleton — import this object everywhere
config = Config.from_env()
