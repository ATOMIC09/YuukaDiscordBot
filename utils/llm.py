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


async def _stream_openrouter(
    messages: list[dict],
    model: str,
    headers: dict,
) -> AsyncGenerator[str, None]:
    """
    Make a single streaming POST to OpenRouter and yield content chunks.
    Raises on network/timeout errors.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    timeout = aiohttp.ClientTimeout(total=180)
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.post(_OPENROUTER_URL, json=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"[LLM] OpenRouter API error {response.status}: {error_text}")
                raise RuntimeError(f"OpenRouter returned status {response.status}")
                
            async for line in response.content:
                line_str = line.decode('utf-8').strip()
                if not line_str:
                    continue
                if line_str == "data: [DONE]":
                    break
                if line_str.startswith("data: "):
                    try:
                        data = json.loads(line_str[6:])
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    except Exception:
                        pass


async def _filter_search_tags(stream: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
    """Filters out any [SEARCH: ...] or [SEARCH_DETAIL: ...] tags from a stream."""
    buffer = ""
    async for chunk in stream:
        buffer += chunk
        
        idx = buffer.rfind("[")
        if idx != -1:
            potential_tag = buffer[idx:]
            
            if "[SEARCH:".startswith(potential_tag) or "[SEARCH_DETAIL:".startswith(potential_tag):
                if idx > 0:
                    yield buffer[:idx]
                buffer = potential_tag
                continue
                
            if potential_tag.startswith("[SEARCH:") or potential_tag.startswith("[SEARCH_DETAIL:"):
                if "]" in potential_tag:
                    if idx > 0:
                        yield buffer[:idx]
                    
                    # Tag complete, silently drop it and keep any text that follows
                    tag_end = potential_tag.find("]") + 1
                    buffer = potential_tag[tag_end:]
                else:
                    if idx > 0:
                        yield buffer[:idx]
                    buffer = potential_tag
                continue
                
        yield buffer
        buffer = ""

    if buffer:
        yield buffer


async def generate_chat_stream_response(messages: list[dict], model: str = None) -> AsyncGenerator[tuple[str, str], None]:
    """
    Send a message history to OpenRouter and yield the AI's response in chunks.

    Implements an agentic web-search loop:
      - Pass 1: LLM may emit a tool_call for web_search.
      - If it does, Tavily is called (1 credit) and results are injected.
      - Pass 2: LLM writes the final grounded answer.
      - If no tool_call in Pass 1, the Pass 1 reply is returned directly (0 Tavily credits).

    Args:
        messages: A list of message dicts (e.g., [{"role": "user", "content": "..."}]).
                  The system prompt should be the first element with role "system".
        model: Override the model to use. Falls back to config.openrouter_model.

    Yields:
        Tuples of (type, text):
            - ("status", "status message")
            - ("content", "text chunk")
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

    logger.debug(f"[LLM] Pass 1 (Stream) → OpenRouter | model={actual_model} | messages={len(messages)}")

    buffer = ""
    search_query = ""
    search_detail_index = None

    try:
        async for chunk in _stream_openrouter(squashed, actual_model, headers):
            buffer += chunk
            
            idx = buffer.rfind("[")
            if idx != -1:
                potential_tag = buffer[idx:]
                
                if "[SEARCH:".startswith(potential_tag) or "[SEARCH_DETAIL:".startswith(potential_tag):
                    if idx > 0:
                        yield ("content", buffer[:idx])
                    buffer = potential_tag
                    continue
                    
                if potential_tag.startswith("[SEARCH:") or potential_tag.startswith("[SEARCH_DETAIL:"):
                    if "]" in potential_tag:
                        if idx > 0:
                            yield ("content", buffer[:idx])
                        
                        search_match = re.search(r'\[SEARCH:\s*(.+?)\]', potential_tag)
                        detail_match = re.search(r'\[SEARCH_DETAIL:\s*(.+?)\s*\|\s*(\d+)\]', potential_tag)
                        
                        if search_match:
                            search_query = search_match.group(1).strip()
                            yield ("status", f"<a:MagnifierGIF:1052563354910216252> ค้นหาข้อมูลบนเว็บ: `{search_query}`...")
                            logger.info(f"[LLM] 🔎 LLM requested SEARCH('{search_query}')")
                            break
                        elif detail_match:
                            search_query = detail_match.group(1).strip()
                            search_detail_index = int(detail_match.group(2))
                            yield ("status", f"<a:AppleLoadingGIF:1052465926487953428> กำลังอ่านรายละเอียดของ: `{search_query}`...")
                            logger.info(f"[LLM] 📖 LLM requested SEARCH_DETAIL('{search_query}', {search_detail_index})")
                            break
                        else:
                            yield ("content", buffer)
                            buffer = ""
                    else:
                        if idx > 0:
                            yield ("content", buffer[:idx])
                        buffer = potential_tag
                    continue
            
            yield ("content", buffer)
            buffer = ""

        if buffer and not search_query:
            yield ("content", buffer)

        if search_query:
            # We broke out early to perform a search
            tool_content = await web_search(search_query, max_results=5, result_index=search_detail_index)
            
            pass2_messages = squashed + [
                {"role": "assistant", "content": buffer.strip()},
                {"role": "user", "content": f"Search Results:\n{tool_content}"},
            ]
            
            yield ("status", "<a:ThinkingSpining:1528490272588038284> หนูอ่านข้อมูลเสร็จแล้ว กำลังเรียบเรียงคำตอบให้ค่ะ")
            logger.debug(f"[LLM] Pass 2 (Stream) → OpenRouter (with search results injected)")
            
            async for chunk in _filter_search_tags(_stream_openrouter(pass2_messages, actual_model, headers)):
                yield ("content", chunk)
                
        logger.info(f"[LLM] ✅ Stream completed successfully")

    except aiohttp.ClientConnectorError:
        logger.error(f"[LLM] Failed to connect to OpenRouter at {_OPENROUTER_URL}")
        yield ("content", "❌ Connection Error: Could not reach OpenRouter. Please check your internet connection.")
    except asyncio.TimeoutError:
        logger.error("[LLM] Request to OpenRouter timed out.")
        yield ("content", "❌ Timeout Error: The AI took too long to respond.")
    except Exception as exc:
        logger.exception(f"[LLM] Unexpected error: {exc}")
        yield ("content", f"❌ Unexpected Error: {exc}")

