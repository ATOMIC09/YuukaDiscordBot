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
    ollama_base_url: str
    ollama_model: str
    ollama_system_prompt: str
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
        
        ollama_base_url = os.getenv("OLLAMA_BASE_URL")
        if not ollama_base_url:
            raise ValueError("OLLAMA_BASE_URL is not set. Please add it to your .env file.")
            
        ollama_model = os.getenv("OLLAMA_MODEL")
        if not ollama_model:
            raise ValueError("OLLAMA_MODEL is not set. Please add it to your .env file.")
            
        ollama_system_prompt = os.getenv("OLLAMA_SYSTEM_PROMPT")
        if not ollama_system_prompt:
            raise ValueError("OLLAMA_SYSTEM_PROMPT is not set. Please add it to your .env file.")

        return cls(
            bot_token=token,
            guild_ids=guild_ids,
            log_level=log_level,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_system_prompt=ollama_system_prompt,
        )


# Singleton — import this object everywhere
config = Config.from_env()
