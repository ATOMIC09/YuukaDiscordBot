"""
utils/ai/agent.py
The agent loop behind /ai: the model picks a tool, we run it, the result goes
back to the model, until it answers in plain text.

Hand-written on purpose. LangChain's own agent runtime pulls in LangGraph, and
this loop is small; the pieces that matter (chat model, tool calls, tools,
messages) are all LangChain core.

`run_agent` yields the events the cogs already handle:
    ("status", str)             a tool is about to run
    ("content", str)            a chunk of her reply
    ("action", ActionResult)    a bot command ran
    ("error", dict | str)       generation failed; nothing follows
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import openai
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage, convert_to_messages
from pydantic import ValidationError

from bot.logger import logger
from utils.ai.context import YuukaContext
from utils.ai.models import chat_model
from utils.ai.tool_calling import ToolPromptChatModel
from utils.ai.tools import status_line, tools_for
from utils.ai_actions import ActionResult
from utils.errors import UserError, UserWarning

# Model calls per turn. The last one runs without tools so she always answers.
MAX_ROUNDS = 4


def _cache_notice() -> str:
    from utils.web_search import get_all_cached_tocs

    count, tocs = get_all_cached_tocs()
    if count == 0:
        return ""
    return (
        "\n\n[CACHED SEARCH RESULTS]\n"
        "You have recently searched the web. The results are below in Table of Contents (TOC) format.\n"
        "If the answer is in these snippets, answer immediately.\n"
        "To read one result in full, call web_search with the same query and its result_index.\n"
        "If the information is NOT in the cache, call web_search with a new query.\n"
        f"--- START CACHE ---\n{tocs}\n--- END CACHE ---"
    )


def _error_event(exc: Exception) -> tuple[str, Any]:
    """Map a failure to the shapes the cogs already show and log."""
    if isinstance(exc, openai.APITimeoutError):
        logger.error("[Agent] Request to OpenRouter timed out.")
        return ("error", "Timeout Error: The AI took too long to respond.")
    if isinstance(exc, openai.APIConnectionError):
        logger.error("[Agent] Failed to connect to OpenRouter.")
        return ("error", "Connection Error: Could not reach OpenRouter. Please check your internet connection.")
    if isinstance(exc, openai.APIStatusError):
        logger.error(f"[Agent] OpenRouter error {exc.status_code}: {exc.message}")
        return ("error", {
            "user": f"Unexpected Error: OpenRouter returned status {exc.status_code}",
            "dev": f"OpenRouter API Error {exc.status_code}\n{exc.message}",
        })
    logger.exception(f"[Agent] Unexpected error: {exc}")
    return ("error", f"Unexpected Error: {exc}")


async def _run_tool(tools: dict, call: dict, ctx: YuukaContext) -> ToolMessage:
    name, call_id = call["name"], call["id"]
    tool = tools.get(name)
    if tool is None:
        return ToolMessage(
            f"No such tool. Available: {', '.join(tools)}", tool_call_id=call_id, name=name
        )

    try:
        return await tool.ainvoke(
            {"type": "tool_call", "id": call_id, "name": name, "args": {**call["args"], "ctx": ctx}}
        )
    except (UserError, UserWarning) as exc:
        return ToolMessage(f"{exc.title}: {exc.description}", tool_call_id=call_id, name=name)
    except ValidationError as exc:
        logger.warning(f"[Agent] Bad arguments for '{name}': {exc}")
        return ToolMessage("Invalid arguments for this tool.", tool_call_id=call_id, name=name)
    except Exception as exc:
        logger.exception(f"[Agent] Tool '{name}' failed: {exc}")
        return ToolMessage("Tool failed.", tool_call_id=call_id, name=name)


async def run_agent(history: list[dict], ctx: YuukaContext) -> AsyncGenerator[tuple[str, Any], None]:
    messages = [dict(m) for m in history]
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] += _cache_notice()
    conversation = convert_to_messages(messages)

    tools = {t.name: t for t in tools_for(ctx)}
    plain = ToolPromptChatModel(inner=chat_model())
    with_tools = plain.bind_tools(list(tools.values())) if tools else plain

    wrote = False
    try:
        for round_no in range(MAX_ROUNDS):
            model = plain if round_no == MAX_ROUNDS - 1 else with_tools
            logger.debug(f"[Agent] Round {round_no + 1}/{MAX_ROUNDS} | messages={len(conversation)}")

            reply: AIMessageChunk | None = None
            separate = wrote
            async for chunk in model.astream(conversation):
                reply = chunk if reply is None else reply + chunk
                if chunk.content:
                    text = chunk.content
                    if separate and text.strip():
                        text, separate = "\n\n" + text.lstrip(), False
                    wrote = wrote or bool(text.strip())
                    yield ("content", text)

            calls = reply.tool_calls if reply is not None and round_no < MAX_ROUNDS - 1 else []
            if not calls:
                break

            conversation.append(AIMessage(content=reply.content, tool_calls=calls))
            stop = False
            for call in calls:
                logger.info(f"[Agent] Tool call: {call['name']}({call['args']})")
                yield ("status", status_line(call["name"], call["args"]))

                result = await _run_tool(tools, call, ctx)
                conversation.append(result)

                if isinstance(result.artifact, ActionResult):
                    yield ("action", result.artifact)
                if tools.get(call["name"]) is not None and tools[call["name"]].return_direct:
                    stop = True
            if stop:
                break

        logger.info("[Agent] Turn completed")
    except Exception as exc:
        yield _error_event(exc)
