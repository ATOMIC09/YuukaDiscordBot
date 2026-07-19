"""
utils/llm.py
Asynchronous client for interacting with OpenRouter's OpenAI-compatible chat API.

Web search is implemented via the standard OpenAI function-calling protocol:
  1. Pass 1 — LLM decides whether to call web_search(query). If yes → search fires (1 Tavily credit).
  2. Pass 2 — Results are injected as a "tool" message; LLM writes the grounded final answer.
If the LLM does not call the tool (normal conversation), no search is made and no credit is spent.
"""

from __future__ import annotations

import asyncio
import json
import re
import aiohttp
from typing import Any

from bot.config import config
from bot.logger import logger

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def _squash_messages(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role (required by some instruct models)."""
    squashed: list[dict] = []
    for msg in messages:
        if squashed and squashed[-1]["role"] == msg["role"]:
            squashed[-1]["content"] += f"\n{msg['content']}"
        else:
            squashed.append({"role": msg["role"], "content": msg["content"]})
    return squashed


async def _call_openrouter(
    messages: list[dict],
    model: str,
    tools: list[dict] | None,
    headers: dict,
) -> dict:
    """
    Make a single POST to OpenRouter and return the parsed JSON response dict.
    Raises on network/timeout errors so the caller can handle them.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    timeout = aiohttp.ClientTimeout(total=60)
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.post(_OPENROUTER_URL, json=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"[LLM] OpenRouter API error {response.status}: {error_text}")
                raise RuntimeError(f"OpenRouter returned status {response.status}")
            return await response.json()


async def generate_chat_response(messages: list[dict], model: str = None) -> str:
    """
    Send a message history to OpenRouter and return the AI's response.

    Implements an agentic web-search loop:
      - Pass 1: LLM may emit a tool_call for web_search.
      - If it does, Tavily is called (1 credit) and results are injected.
      - Pass 2: LLM writes the final grounded answer.
      - If no tool_call in Pass 1, the Pass 1 reply is returned directly (0 Tavily credits).

    Args:
        messages: A list of message dicts (e.g., [{"role": "user", "content": "..."}]).
                  The system prompt should be the first element with role "system".
        model: Override the model to use. Falls back to config.openrouter_model.

    Returns:
        The generated text response, or an error message string if the call fails.
    """
    from utils.web_search import web_search

    actual_model = model or config.openrouter_model
    squashed = _squash_messages(messages)

    if squashed and squashed[0]["role"] == "system":
        search_instruction = (
            "\n\n[SYSTEM INSTRUCTION]\n"
            "You have access to a web search tool. To use it, you MUST reply EXACTLY with this format on a single line:\n"
            "[SEARCH: your search query]\n"
            "To read a specific search result in full, reply with:\n"
            "[SEARCH_DETAIL: your search query | result_index]\n"
            "Do not include any other text if you are triggering a search."
        )
        squashed[0]["content"] += search_instruction

    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ATOMIC09/YuukaDiscordBot",
        "X-Title": "Yuuka-Bot",
    }

    logger.debug(
        f"[LLM] Pass 1 → OpenRouter | model={actual_model} | messages={len(messages)}"
    )

    try:
        # ── Pass 1: Let the LLM decide whether to search ────────────────────────
        data = await _call_openrouter(squashed, actual_model, None, headers)

        choices = data.get("choices", [])
        if not choices:
            logger.error(f"[LLM] No choices returned (Pass 1): {data}")
            return "❌ AI Error: No response generated."

        message = choices[0].get("message", {})
        reply = message.get("content", "").strip()

        # ── Parse Custom Tool Calling ─────────────────────────────────────────
        search_match = re.search(r'\[SEARCH:\s*(.+?)\]', reply)
        detail_match = re.search(r'\[SEARCH_DETAIL:\s*(.+?)\s*\|\s*(\d+)\]', reply)

        if not search_match and not detail_match:
            logger.info(f"[LLM] ✅ Reply (no search) — {len(reply)} chars")
            logger.debug(f"[LLM] Full response: {data}")
            return reply

        # ── Tool call detected → execute web search ──────────────────────────────
        query = ""
        result_index = None

        if detail_match:
            query = detail_match.group(1).strip()
            result_index = int(detail_match.group(2))
            logger.info(f"[LLM] 📖 LLM requested SEARCH_DETAIL('{query}', {result_index})")
        elif search_match:
            query = search_match.group(1).strip()
            logger.info(f"[LLM] 🔎 LLM requested SEARCH('{query}')")

        tool_content = await web_search(query, max_results=5, result_index=result_index)

        # ── Pass 2: Feed results back and get the final grounded answer ──────────
        pass2_messages = squashed + [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"Search Results:\n{tool_content}"},
        ]

        logger.debug(f"[LLM] Pass 2 → OpenRouter (with search results injected)")
        data2 = await _call_openrouter(pass2_messages, actual_model, None, headers)

        choices2 = data2.get("choices", [])
        if not choices2:
            logger.error(f"[LLM] No choices returned (Pass 2): {data2}")
            return "❌ AI Error: No response generated after search."

        final_reply = choices2[0].get("message", {}).get("content", "").strip()
        logger.info(f"[LLM] ✅ Reply (with search) — {len(final_reply)} chars")
        logger.debug(f"[LLM] Full response (Pass 2): {data2}")
        return final_reply

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
