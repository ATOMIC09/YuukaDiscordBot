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
    ("done", list[dict])        a tool that ends the turn succeeded: its call and result, as
                                history entries (the turn has no text to record otherwise)
    ("error", dict | str)       generation failed; nothing follows
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import openai
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
    convert_to_messages,
)
from pydantic import ValidationError

from bot.logger import logger
from utils.ai.context import YuukaContext
from utils.ai.linker import ChannelLinker
from utils.ai.models import chat_model
from utils.ai.tool_calling import FABRICATED, ToolPromptChatModel
from utils.ai.tools import music, status_line, tools_for
from utils.ai_actions import ActionResult
from utils.errors import UserError, UserWarning

# Model calls per turn. The last one runs without tools so she always answers.
MAX_ROUNDS = 4

_FABRICATED_NOTE = (
    "[SYSTEM] You wrote a <tool_response> yourself. Only the system writes those; what you "
    "wrote is made up and was not shown. Call the tool with <tool_call>...</tool_call> and "
    "wait for the real result, or answer without it."
)

_LAST_ROUND_NOTE = (
    "[SYSTEM] No more tools this turn. Answer the user now, in your normal voice and their "
    "language, using only the results above. If you could not get what they asked for, "
    "say so briefly and why. Do not describe what you would do next."
)

_EMPTY_REPLY = "หนูนึกคำตอบไม่ออกค่ะ เซนเซย์ลองถามใหม่อีกทีนะคะ (´・ω・`)"


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


async def _run_tool(tools: dict, call: dict, ctx: YuukaContext) -> tuple[ToolMessage, bool]:
    """Run one tool call. The flag is False when it failed or was refused."""
    name, call_id = call["name"], call["id"]
    tool = tools.get(name)
    if tool is None:
        message = ToolMessage(
            f"No such tool. Available: {', '.join(tools)}", tool_call_id=call_id, name=name
        )
        return message, False

    try:
        message = await tool.ainvoke(
            {"type": "tool_call", "id": call_id, "name": name, "args": {**call["args"], "ctx": ctx}}
        )
        return message, True
    except (UserError, UserWarning) as exc:
        return ToolMessage(f"{exc.title}: {exc.description}", tool_call_id=call_id, name=name), False
    except ValidationError as exc:
        logger.warning(f"[Agent] Bad arguments for '{name}': {exc}")
        return ToolMessage("Invalid arguments for this tool.", tool_call_id=call_id, name=name), False
    except Exception as exc:
        logger.exception(f"[Agent] Tool '{name}' failed: {exc}")
        return ToolMessage("Tool failed.", tool_call_id=call_id, name=name), False


async def run_agent(history: list[dict], ctx: YuukaContext) -> AsyncGenerator[tuple[str, Any], None]:
    tools = {t.name: t for t in tools_for(ctx)}

    messages = [dict(m) for m in history]
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] += _cache_notice()
        if "music_play" in tools:
            messages[0]["content"] += music.now_playing_notice(ctx)
    conversation = convert_to_messages(messages)

    plain = ToolPromptChatModel(inner=chat_model())
    with_tools = plain.bind_tools(list(tools.values())) if tools else plain

    # Text only: a mention read aloud is just digits.
    linker = None if ctx.voice else ChannelLinker(ctx.channels_used)

    wrote = False
    retried = False
    try:
        for round_no in range(MAX_ROUNDS):
            last = round_no == MAX_ROUNDS - 1
            model = plain if last else with_tools
            if last:
                # Without this the model plans its next tool call out loud as the reply.
                conversation.append(HumanMessage(content=_LAST_ROUND_NOTE))
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
                    if linker is not None:
                        text = linker.feed(text)
                    if text:
                        yield ("content", text)
            if linker is not None and (rest := linker.flush()):
                yield ("content", rest)

            calls = reply.tool_calls if reply is not None and not last else []
            if not calls:
                # She wrote a tool's result herself instead of calling it: send her back
                # once (this round already counts) rather than answer from invented data.
                if reply is not None and reply.additional_kwargs.get(FABRICATED) and not last:
                    conversation.append(AIMessage(content=reply.content))
                    conversation.append(HumanMessage(content=_FABRICATED_NOTE))
                    continue
                # Nothing at all to show. Usually a one-off, so ask once more (the
                # round still counts); a second empty reply is reported, not retried.
                if not wrote and not (reply is not None and str(reply.content).strip()):
                    if not retried and not last:
                        retried = True
                        logger.warning("[Agent] Empty reply; asking again")
                        continue
                    yield ("error", {"user": _EMPTY_REPLY, "dev": "The model returned an empty reply."})
                    return
                break

            conversation.append(AIMessage(content=reply.content, tool_calls=calls))
            stop = False
            for index, call in enumerate(calls):
                logger.info(f"[Agent] Tool call: {call['name']}({call['args']})")
                yield ("status", status_line(call["name"], call["args"]))

                result, ok = await _run_tool(tools, call, ctx)
                conversation.append(result)

                action = result.artifact if isinstance(result.artifact, ActionResult) else None
                if action is not None:
                    yield ("action", action)
                # A terminal tool ends the turn only when it worked; a refusal
                # goes back to the model so she can explain it.
                if ok and tools[call["name"]].return_direct:
                    stop = True
                    # Such a turn writes no text, so without this the history would hold
                    # the request and nothing after it, and the model would do it again
                    # on the next message. Kept as a real call and result, the format she
                    # is prompted with: any other note she copies into her replies
                    # instead of calling the tool.
                    yield ("done", [
                        {"role": "assistant", "content": "", "tool_calls": [
                            {"name": call["name"], "args": call["args"], "id": call["id"], "type": "tool_call"}
                        ]},
                        {"role": "tool", "content": str(result.content), "tool_call_id": call["id"], "name": call["name"]},
                    ])
                # Calls in one reply are a sequence ("queue it, then skip"): after a
                # failure the rest no longer make sense.
                if not ok or (action is not None and not action.ok):
                    for skipped in calls[index + 1 :]:
                        logger.info(f"[Agent] Skipped after a failure: {skipped['name']}")
                        conversation.append(ToolMessage(
                            "Not run: an earlier call in the same reply failed.",
                            tool_call_id=skipped["id"],
                            name=skipped["name"],
                        ))
                    break
            if stop:
                break

        logger.info("[Agent] Turn completed")
    except Exception as exc:
        yield _error_event(exc)
