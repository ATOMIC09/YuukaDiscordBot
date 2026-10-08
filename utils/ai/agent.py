"""
utils/ai/agent.py
The agent loop behind /ai: the model picks a tool, we run it, the result goes
back to the model, until it answers in plain text.

Hand-written on purpose. LangChain's own agent runtime pulls in LangGraph, and
this loop is small; the pieces that matter (chat model, tool calls, tools,
messages) are all LangChain core.

`run_agent` yields the events the cogs already handle:
    ("thinking", (int, int))    a round starts: its number and the most rounds a turn may take
    ("plan", list[dict])        the calls the model chose this round, {"name", "args"}, in order
    ("step", (int, str))        call number (in that plan) and its state: running, ok, failed, skipped
    ("status", str)             a tool is about to run
    ("content", str)            a chunk of her reply
    ("action", ActionResult)    a bot command ran
    ("done", list[dict])        a tool that ends the turn succeeded: its call and result, as
                                history entries (the turn has no text to record otherwise)
    ("error", dict | str)       generation failed; nothing follows
"""

from __future__ import annotations

import json
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

from bot.config import config
from bot.logger import logger
from utils.ai.context import YuukaContext
from utils.ai.linker import ChannelLinker
from utils.ai.models import chat_model
from utils.ai.tool_calling import FABRICATED, ToolPromptChatModel
from utils.ai.tools import PRIVATE_ARGS, READ_ONLY, memory, music, status_line, tools_for
from utils.ai_actions import ActionResult
from utils.errors import UserError, UserWarning

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

_RETRY_NOTE = (
    "[SYSTEM] Your last reply had no usable tool call and no answer. Either write the tool "
    "call now, exactly as <tool_call>{...}</tool_call> with valid JSON, or answer the user directly."
)

_EMPTY_REPLY = "หนูนึกคำตอบไม่ออกค่ะ เซนเซย์ลองถามใหม่อีกทีนะคะ (´・ω・`)"


def _cache_notice() -> str:
    """Names the earlier searches, never their results: this rides on every request."""
    from utils.web_search import cached_queries

    queries = cached_queries()
    if not queries:
        return ""
    listed = "; ".join(f'"{q}"' for q in queries)
    return (
        "\n\n[CACHED SEARCHES] Searched recently, newest first: "
        f"{listed}.\n"
        "To read one again (free), call web_search with that exact query. "
        "Search a new query only when none of these fits."
    )


async def _with_memory(messages: list[dict], ctx: YuukaContext) -> bool:
    """Put the server's notes that bear on the request in front of it, as a user message of their own.
    True when a note was added.

    Members wrote the notes, so they get a user's trust and not the system prompt's. In front of
    the request, not after it, because the reply language is read off the last user message."""
    notice = await memory.memory_notice(ctx, messages)
    if not notice:
        return False
    for index in range(len(messages) - 1, 0, -1):
        if messages[index]["role"] == "user":
            messages.insert(index, {"role": "user", "content": notice})
            return True
    return False


class _EchoFilter:
    """Cuts a copy of the [MEMORY] block off the start of a reply.

    The block is a user turn, and a model sometimes takes it for part of the message and repeats
    it before answering (seen on the free model). Left in, it would be posted in the chat, or
    read aloud in a call. The block is the "[MEMORY]" line and the "- " lines under it; the
    reply starts at the first line that is neither."""

    _HEAD = "[MEMORY]"

    def __init__(self) -> None:
        self._buffer = ""
        self._state = "start"  # start: not sure yet, echo: inside the block, pass: nothing to cut

    @staticmethod
    def _in_block(line: str) -> bool:
        line = line.strip()
        return not line or line.startswith("[MEMORY]") or line.startswith("- ")

    def feed(self, text: str) -> str:
        if self._state == "pass":
            return text
        self._buffer += text
        if self._state == "start":
            seen = self._buffer.lstrip()
            if len(seen) < len(self._HEAD) and self._HEAD.startswith(seen):
                return ""  # could still turn out to be the block
            if not seen.startswith(self._HEAD):
                self._state, out, self._buffer = "pass", self._buffer, ""
                return out
            self._state = "echo"
        while "\n" in self._buffer:
            line, rest = self._buffer.split("\n", 1)
            if self._in_block(line):
                self._buffer = rest
                continue
            self._state, out, self._buffer = "pass", self._buffer, ""
            return out
        return ""

    def flush(self) -> str:
        """Whatever is still held when the reply ends."""
        out = "" if self._state == "echo" and self._in_block(self._buffer) else self._buffer
        self._buffer = ""
        return out


def _logged_args(name: str, args: dict) -> str:
    """A call's arguments for a log line. A tool that carries a server's notes logs none: the
    log file outlives the reply."""
    return "…" if name in PRIVATE_ARGS else str(args)


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
        # The error quotes the input, which for a memory tool is the note.
        logger.warning(f"[Agent] Bad arguments for '{name}': {'…' if name in PRIVATE_ARGS else exc}")
        return ToolMessage("Invalid arguments for this tool.", tool_call_id=call_id, name=name), False
    except Exception as exc:
        logger.exception(f"[Agent] Tool '{name}' failed: {type(exc).__name__ if name in PRIVATE_ARGS else exc}")
        return ToolMessage("Tool failed.", tool_call_id=call_id, name=name), False


async def run_agent(history: list[dict], ctx: YuukaContext) -> AsyncGenerator[tuple[str, Any], None]:
    tools = {t.name: t for t in tools_for(ctx)}

    messages = [dict(m) for m in history]
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] += _cache_notice()
        if "music_play" in tools:
            messages[0]["content"] += music.now_playing_notice(ctx)
    noted = await _with_memory(messages, ctx)
    conversation = convert_to_messages(messages)

    plain = ToolPromptChatModel(inner=chat_model())
    with_tools = plain.bind_tools(list(tools.values())) if tools else plain

    # Text only: a mention read aloud is just digits.
    linker = None if ctx.voice else ChannelLinker(ctx.channels_used)

    wrote = False
    retried = False
    try:
        # The last round runs without tools so she always answers.
        max_rounds = config.agent_max_rounds
        for round_no in range(max_rounds):
            last = round_no == max_rounds - 1
            model = plain if last else with_tools
            if last:
                # Without this the model plans its next tool call out loud as the reply.
                conversation.append(HumanMessage(content=_LAST_ROUND_NOTE))
            logger.debug(f"[Agent] Round {round_no + 1}/{max_rounds} | messages={len(conversation)}")
            yield ("thinking", (round_no + 1, max_rounds))

            reply: AIMessageChunk | None = None
            separate = wrote
            echo = _EchoFilter() if noted else None
            async for chunk in model.astream(conversation):
                reply = chunk if reply is None else reply + chunk
                text = echo.feed(chunk.content) if echo is not None and chunk.content else chunk.content
                if text:
                    if separate and text.strip():
                        text, separate = "\n\n" + text.lstrip(), False
                    wrote = wrote or bool(text.strip())
                    if linker is not None:
                        text = linker.feed(text)
                    if text:
                        yield ("content", text)
            if echo is not None and (held := echo.flush()):
                wrote = wrote or bool(held.strip())
                yield ("content", linker.feed(held) if linker is not None else held)
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
                        conversation.append(HumanMessage(content=_RETRY_NOTE))
                        continue
                    yield ("error", {"user": _EMPTY_REPLY, "dev": "The model returned an empty reply."})
                    return
                break

            conversation.append(AIMessage(content=reply.content, tool_calls=calls))

            # The model sometimes writes the same lookup several times in one reply
            # (reading result 0 three times). Run it once: the others get a note.
            seen: set[str] = set()
            duplicate: set[int] = set()
            for position, call in enumerate(calls):
                if call["name"] not in READ_ONLY:
                    continue
                key = f"{call['name']}:{json.dumps(call['args'], sort_keys=True, ensure_ascii=False)}"
                if key in seen:
                    duplicate.add(position)
                seen.add(key)
            planned = [c for position, c in enumerate(calls) if position not in duplicate]
            yield ("plan", [{"name": c["name"], "args": c["args"]} for c in planned])

            stop = False
            index = -1  # position among the planned calls, which is what the "step" events number
            for position, call in enumerate(calls):
                if position in duplicate:
                    logger.info(f"[Agent] Skipped a repeated call: {call['name']}({_logged_args(call['name'], call['args'])})")
                    conversation.append(ToolMessage(
                        "Same call as an earlier one in this reply: use that result.",
                        tool_call_id=call["id"],
                        name=call["name"],
                    ))
                    continue
                index += 1
                logger.info(f"[Agent] Tool call: {call['name']}({_logged_args(call['name'], call['args'])})")
                yield ("step", (index, "running"))
                yield ("status", status_line(call["name"], call["args"]))

                result, ok = await _run_tool(tools, call, ctx)
                conversation.append(result)

                action = result.artifact if isinstance(result.artifact, ActionResult) else None
                if action is not None:
                    yield ("action", action)
                worked = ok and (action is None or action.ok)
                yield ("step", (index, "ok" if worked else "failed"))
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
                if not worked:
                    offset = index
                    for later, skipped in enumerate(calls[position + 1 :], start=position + 1):
                        logger.info(f"[Agent] Skipped after a failure: {skipped['name']}")
                        if later not in duplicate:
                            offset += 1
                            yield ("step", (offset, "skipped"))
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
