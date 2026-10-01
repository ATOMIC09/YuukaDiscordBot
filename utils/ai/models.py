"""
utils/ai/models.py
The OpenRouter chat model, built once per call so config changes are picked up.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from bot.config import config

_OPENROUTER_URL = "https://openrouter.ai/api/v1"


def chat_model() -> ChatOpenAI:
    """A streaming-capable client for the configured OpenRouter model."""
    return ChatOpenAI(
        model=config.openrouter_model,
        base_url=_OPENROUTER_URL,
        api_key=config.openrouter_api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/ATOMIC09/YuukaDiscordBot",
            "X-Title": "Yuuka-Bot",
        },
        timeout=180,
        max_retries=1,
    )
