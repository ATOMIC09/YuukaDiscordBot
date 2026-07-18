"""
utils/llm.py
Asynchronous client for interacting with OpenRouter's OpenAI-compatible chat API.
"""

from __future__ import annotations

import asyncio
import aiohttp
from typing import Any

from bot.config import config
from bot.logger import logger

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def generate_chat_response(messages: list[dict], model: str = None) -> str:
    """
    Send a message history to OpenRouter and return the AI's response.

    Args:
        messages: A list of message dicts (e.g., [{"role": "user", "content": "..."}]).
                  The system prompt should be the first element with role "system".
        model: Override the model to use. Falls back to config.ollama_model.

    Returns:
        The generated text response, or an error message string if the call fails.
    """
    actual_model = model or config.openrouter_model

    # 
    squashed_messages: list[dict] = []
    for msg in messages:
        if squashed_messages and squashed_messages[-1]["role"] == msg["role"]:
            squashed_messages[-1]["content"] += f"\n{msg['content']}"
        else:
            squashed_messages.append({"role": msg["role"], "content": msg["content"]})

    payload = {
        "model": actual_model,
        "messages": squashed_messages,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ATOMIC09/YuukaDiscordBot",
        "X-Title": "Yuuka-Bot",
    }

    logger.debug(
        f"[LLM] Sending request to OpenRouter | model={actual_model} | "
        f"messages={len(messages)}"
    )
    logger.debug(f"[LLM] Payload: {payload}")

    try:
        timeout = aiohttp.ClientTimeout(total=60)
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(
                _OPENROUTER_URL, json=payload, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    choices = data.get("choices", [])
                    if not choices:
                        logger.error(f"[LLM] No choices returned: {data}")
                        return "❌ AI Error: No response generated."
                    reply_text = (
                        choices[0].get("message", {}).get("content", "").strip()
                    )
                    logger.info(f"[LLM] Received response ({len(reply_text)} chars)")
                    logger.debug(f"[LLM] Full response: {data}")
                    return reply_text
                else:
                    error_text = await response.text()
                    logger.error(
                        f"[LLM] OpenRouter API error {response.status}: {error_text}"
                    )
                    return f"❌ AI Error: OpenRouter returned status {response.status}."

    except aiohttp.ClientConnectorError:
        logger.error(f"[LLM] Failed to connect to OpenRouter at {_OPENROUTER_URL}") 
        return (
            "❌ Connection Error: Could not reach OpenRouter. "
            "Please check your internet connection."
        )
    except asyncio.TimeoutError:
        logger.error("[LLM] Request to OpenRouter timed out.")
        return "❌ Timeout Error: The AI took too long to respond."
    except Exception as exc:
        logger.exception(f"[LLM] Unexpected error: {exc}")
        return f"❌ Unexpected Error: {exc}"
