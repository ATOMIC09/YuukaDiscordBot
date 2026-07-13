"""
utils/llm.py
Asynchronous client for interacting with a local Ollama instance.
"""

from __future__ import annotations

import asyncio
import aiohttp
from typing import Any

from bot.config import config
from bot.logger import logger

async def generate_chat_response(messages: list[dict], model: str = None) -> str:
    """
    Send a message history to the external Ollama container and return the AI's response.
    
    Args:
        messages: A list of message dicts (e.g., [{"role": "user", "content": "..."}]).
                  The SYSTEM_PROMPT should be the first element.
        model: The Ollama model to use.
        
    Returns:
        The generated text response, or an error message if the call fails.
    """
    url = f"{config.ollama_base_url.rstrip('/')}/api/chat"
    
    # Use the model passed in, or fallback to the one in config
    actual_model = model or config.ollama_model
    
    # Most instruct models (like Qwen) expect strict User -> Assistant -> User alternating turns.
    squashed_messages = []
    for msg in messages:
        if squashed_messages and squashed_messages[-1]["role"] == msg["role"]:
            squashed_messages[-1]["content"] += f"\n{msg['content']}"
        else:
            # Create a new dict so we don't accidentally mutate the original history
            squashed_messages.append({"role": msg["role"], "content": msg["content"]})
    
    payload = {
        "model": actual_model,
        "messages": squashed_messages,
        "stream": False,
        "options": {
            "num_ctx": 65536
        }
    }

    logger.debug(f"[LLM] Sending request to {url} with model {actual_model} ({len(messages)} messages)")
    logger.debug(f"[LLM] Outgoing Payload: {payload}")
    
    try:
        # 60-second timeout. CPU inference can take a bit if the model is loading.
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    message = data.get("message", {})
                    reply_text = message.get("content", "").strip()
                    logger.info(f"[LLM] Received response ({len(reply_text)} chars)")
                    logger.debug(f"[LLM] Full Response: {data}")
                    # logger.debug(f"[LLM] Extracted Reply: {reply_text}")
                    return reply_text
                else:
                    error_text = await response.text()
                    logger.error(f"[LLM] API Error {response.status}: {error_text}")
                    return f"❌ AI Error: Ollama returned status {response.status}"
                    
    except aiohttp.ClientConnectorError:
        logger.error(f"[LLM] Failed to connect to Ollama at {url}")
        return (
            "❌ Connection Error: Could not connect to the local AI model. "
            "Please ensure Ollama is running and accessible."
        )
    except asyncio.TimeoutError:
        logger.error("[LLM] Request timed out.")
        return "❌ Timeout Error: The AI took too long to respond."
    except Exception as exc:
        logger.exception(f"[LLM] Unexpected error: {exc}")
        return f"❌ Unexpected Error: {exc}"
