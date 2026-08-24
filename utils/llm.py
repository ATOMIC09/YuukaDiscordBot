"""
utils/llm.py
Asynchronous client for interacting with OpenRouter's OpenAI-compatible chat API.

Tool use is expressed as inline text tags rather than the provider's
function-calling API, so it works on any OpenRouter model regardless of whether
that model advertises tool support. Two families exist, and both are stripped
from the stream before a single character reaches the user:

  [SEARCH: query] / [SEARCH_DETAIL: query | index]
      Web search. Pass 1 decides whether to search; if it does, Tavily is
      called (1 credit) and the results are injected for a grounded pass 2.
      No tag means no search and no credit spent.

  [ACTION: name | argument]
      Run one of the bot's own Discord commands on the user's behalf — see
      `utils.ai_actions` for the registry of what `name` may be. Any prose the
      model writes *before* the tag is kept and becomes the spoken/posted
      acknowledgement, so the caller gets both an utterance and an intent from
      a single pass. Generation stops at the tag: whatever the action does next
      is the caller's business, not the model's.
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

# Every control tag the streaming scanners must intercept. The scanners work a
# character at a time on a partially-received buffer, so they need both "could
# this still become a tag?" and "has this committed to being one?" — hence the
# two helpers rather than a single regex.
_TAG_PREFIXES = ("[SEARCH:", "[SEARCH_DETAIL:", "[ACTION:")

_ACTION_RE = re.compile(r"\[ACTION:\s*([A-Za-z_]+)\s*(?:\|\s*(.*?)\s*)?\]", re.DOTALL)


def _is_partial_tag(text: str) -> bool:
    """True while `text` could still grow into one of the control tags."""
    return any(prefix.startswith(text) for prefix in _TAG_PREFIXES)


def _has_tag_prefix(text: str) -> bool:
    """True once `text` has committed to being a control tag."""
    return any(text.startswith(prefix) for prefix in _TAG_PREFIXES)


class OpenRouterAPIError(Exception):
    def __init__(self, status: int, error_msg: str):
        self.status = status
        self.error_msg = error_msg
        super().__init__(f"OpenRouter returned status {status}")


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
                try:
                    error_json = json.loads(error_text)
                    error_msg = error_json.get("error", {}).get("message", error_text)
                except Exception:
                    error_msg = error_text
                raise OpenRouterAPIError(response.status, error_msg)
                
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
            
            if _is_partial_tag(potential_tag):
                if idx > 0:
                    yield buffer[:idx]
                buffer = potential_tag
                continue

            if _has_tag_prefix(potential_tag):
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


async def generate_chat_stream_response(
    messages: list[dict],
    model: str = None,
    action_catalog: str = "",
) -> AsyncGenerator[tuple[str, Any], None]:
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
        action_catalog: Rendered list of the `[ACTION: ...]` tags this caller can
            actually execute (see `utils.ai_actions.catalog_for`). Empty means the
            model is never told actions exist and so cannot request one — which is
            exactly what a caller with nowhere to run them wants.

    Yields:
        Tuples of (type, payload):
            - ("status", "status message")
            - ("content", "text chunk")
            - ("action", {"name": str, "arg": str})  — terminal, nothing follows it
    """
    from utils.web_search import web_search, get_all_cached_tocs

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

        if action_catalog:
            # Unlike SEARCH, an action tag is deliberately preceded by prose:
            # the caller speaks (or posts) that sentence as the acknowledgement,
            # so the user still gets a reply even though generation stops dead
            # at the tag.
            search_instruction += (
                "\n\nYou can also run the bot's own Discord commands for the user. "
                "To do so, write ONE short sentence acknowledging the request in your "
                "normal voice, then the tag, and then nothing at all:\n"
                f"{action_catalog}\n"
                "Rules for actions:\n"
                "- Only use an action when the user clearly asks for it. Talking "
                "about music is not the same as asking for it to be played.\n"
                "- Never invent a song title the user did not name.\n"
                "- At most ONE action tag per reply, and it must be the last thing "
                "you write.\n"
                "- Do not describe the tag or mention that you are using one."
            )
        
        toc_count, tocs_str = get_all_cached_tocs()
        if toc_count > 0:
            search_instruction += (
                f"\n\n[CACHED SEARCH RESULTS]\n"
                f"You have recently searched the web. The results are available below in Table of Contents (TOC) format.\n"
                f"If the answer to the user's question is present in these snippets, you can answer immediately.\n"
                f"If you need to read the full content of a specific result, use [SEARCH_DETAIL: query | result_index].\n"
                f"If the information is NOT in the cache, you can use [SEARCH: new query] to search the web.\n"
                f"--- START CACHE ---\n{tocs_str}\n--- END CACHE ---"
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
    action: dict[str, str] | None = None

    try:
        async for chunk in _stream_openrouter(squashed, actual_model, headers):
            buffer += chunk
            
            idx = buffer.rfind("[")
            if idx != -1:
                potential_tag = buffer[idx:]
                
                if _is_partial_tag(potential_tag):
                    if idx > 0:
                        yield ("content", buffer[:idx])
                    buffer = potential_tag
                    continue
                    
                if _has_tag_prefix(potential_tag):
                    if "]" in potential_tag:
                        if idx > 0:
                            yield ("content", buffer[:idx])
                        
                        search_match = re.search(r'\[SEARCH:\s*(.+?)\]', potential_tag)
                        detail_match = re.search(r'\[SEARCH_DETAIL:\s*(.+?)\s*\|\s*(\d+)\]', potential_tag)
                        
                        action_match = _ACTION_RE.search(potential_tag)

                        if action_match:
                            action = {
                                "name": action_match.group(1).strip().lower(),
                                "arg": (action_match.group(2) or "").strip(),
                            }
                            # Whatever preceded the tag was already yielded as
                            # content and becomes the acknowledgement. Drop the
                            # tag itself so it can never reach TTS or a message.
                            buffer = ""
                            logger.info(
                                f"[LLM] 🎛️ LLM requested ACTION('{action['name']}'"
                                f"{', ' + action['arg'] if action['arg'] else ''})"
                            )
                            yield ("action", action)
                            break
                        elif search_match:
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

        if buffer and not search_query and action is None:
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

    except OpenRouterAPIError as exc:
        logger.error(f"[LLM] OpenRouter error: {exc.error_msg}")
        yield ("error", {
            "user": f"Unexpected Error: OpenRouter returned status {exc.status}",
            "dev": f"OpenRouter API Error {exc.status}\n{exc.error_msg}"
        })
    except aiohttp.ClientConnectorError:
        logger.error(f"[LLM] Failed to connect to OpenRouter at {_OPENROUTER_URL}")
        yield ("error", "Connection Error: Could not reach OpenRouter. Please check your internet connection.")
    except asyncio.TimeoutError:
        logger.error("[LLM] Request to OpenRouter timed out.")
        yield ("error", "Timeout Error: The AI took too long to respond.")
    except Exception as exc:
        logger.exception(f"[LLM] Unexpected error: {exc}")
        yield ("error", f"Unexpected Error: {exc}")

