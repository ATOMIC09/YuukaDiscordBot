"""
bot/config.py
Loads environment variables from .env and exposes a typed Config dataclass.
Import the singleton `config` object — never access os.environ directly elsewhere.

OpenRouter settings use the `OPENROUTER_*` env var prefix.
Legacy `OLLAMA_*` vars are left in .env for optional local Ollama use.
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
    openrouter_api_key: str
    openrouter_model: str
    openrouter_system_prompt: str
    max_history_length: int
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

        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Add your OpenRouter API key to .env."
            )

        openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/free")

        openrouter_system_prompt = os.getenv("OPENROUTER_SYSTEM_PROMPT")
        if not openrouter_system_prompt:
            raise ValueError(
                "OPENROUTER_SYSTEM_PROMPT is not set. Please add it to your .env file."
            )

        max_history_length = int(os.getenv("MAX_HISTORY_LENGTH", "50"))

        return cls(
            bot_token=token,
            guild_ids=guild_ids,
            log_level=log_level,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
            openrouter_system_prompt=openrouter_system_prompt,
            max_history_length=max_history_length,
        )


# Singleton — import this object everywhere
config = Config.from_env()
