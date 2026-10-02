"""
utils/ai/tool_calling.py
Tool calling for a chat model that has no native tool-call support.

The free OpenRouter model Yuuka runs on rejects the `tools` parameter, so tools
are described to it in the prompt and it answers in plain text:

    <tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>

`ToolPromptChatModel` wraps any chat model and turns that text back into a
standard `AIMessage.tool_calls`, so everything above it (tools, the agent loop)
is ordinary LangChain and would work unchanged on a model with native tools.

gpt-oss models sometimes fall back to their native "harmony" format instead,
and some providers pass its special tokens through as text:

    <|start|>assistant<|channel|>commentary to=functions.web_search<|message|>{...}<|call|>

That is parsed as a call too. A model may also write a <tool_response> itself
instead of waiting for the real one; the stream is cut there and the reply is
flagged with `FABRICATED` so the agent can send it back.

Call text is never yielded as content: it must not reach Discord or TTS. Nor is
text the model writes before a call, which is usually its reasoning.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncIterator, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.chat_models import agenerate_from_stream
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.utils.json import parse_partial_json

from bot.logger import logger

_OPEN = "<tool_call>"
_CLOSE = "</tool_call>"

# Harmony special tokens. Any of them starts a block that is never shown;
# `<|call|>` ends a call.
_HARMONY_OPENERS = ("<|start|>", "<|channel|>", "<|constrain|>", "<|message|>", "<|call|>")
_HARMONY_CALL = "<|call|>"
_HARMONY_TOKEN = re.compile(r"<\|[a-z]+\|>")
_HARMONY_RECIPIENT = re.compile(r"to=([\w.\-]+)")
_HARMONY_FINAL = re.compile(r"<\|channel\|>\s*final\b.*?<\|message\|>(.*)", re.S)

# Only we write tool responses. One from the model is invented.
_FAKE_RESPONSE = "<tool_response"
FABRICATED = "fabricated_tool_response"

# Call and result markup in her earlier replies. A broken reply saved to history
# (or reread from the channel) would otherwise teach the model to repeat it.
_PROTOCOL = re.compile(
    r"<tool_call>.*?(?:</tool_call>|$)"
    r"|<tool_response\b.*?(?:</tool_response>|$)"
    r"|<\|(?:start|channel|constrain|message)\|>.*?(?:<\|call\|>|$)",
    re.S,
)

_TOOL_INSTRUCTIONS = """

[TOOLS]
You can use tools. Available tools (JSON schema for each):
{tools}

To use a tool, reply with ONLY the call, inside the tags exactly as shown, with nothing else around it:
<tool_call>{{"name": "<tool name>", "arguments": {{...}}}}</tool_call>

To do several things in order (for example queue a song, then skip the current one), write up to {max_calls} calls one after another. They run in that order, and the rest are skipped if one fails.{final}

The result comes back as a message of the form <tool_response name="...">...</tool_response>.
Use it to answer the user, or call another tool if you still need something.

Rules:
- Only use a tool when the user clearly asks for it or you truly need it. Talking about something is not the same as asking for it.
- Several calls only when the user asked for several things. A call that needs an earlier call's result must wait for it, in your next reply.
- Never write a <tool_response> yourself, and never guess what a tool would return. Only the system sends results.
- Never describe the call format or mention that you are using tools.
- Never invent arguments the user did not give and no earlier tool result provided.
- A line starting with [result] in an earlier assistant turn is the system's record of something already done. Never write one yourself: to do something, call the tool."""


# Text before a call is never shown: gpt-oss fills it with its reasoning ("We need
# to read the channel."). A reply that gets longer than this with no call in sight
# is an answer, and starts streaming.
_PREAMBLE_CHARS = 300

# Calls one reply may make ("play it, queue Beat It, wait 10 s, skip"). Reading stops
# at the last, so a model that keeps going cannot run a long list.
_MAX_CALLS = 5

# After a long tool result in mixed languages, gpt-oss drifts into a language
# nobody used (Chinese) partway through a reply. Naming the language works better
# than "the user's language".
_THAI = re.compile("[\\u0e00-\\u0e7f]")  # the Thai block
_REPLY_THAI = (
    "(ตอบเป็นภาษาไทยเท่านั้น: reply in Thai only. Quoting messages as they were written is "
    "fine, but every sentence of your own must be Thai. Never switch to Chinese or any "
    "other language partway through.)"
)
_REPLY_SAME = (
    "(Reply only in the language of the user's request, whatever language the results "
    "above are in. Never switch to Chinese or any other language partway through.)"
)


# gpt-oss sometimes stops after its reasoning ("We need to output tool call.") without
# writing the call. Only English that opens like reasoning or names a tool call counts;
# her replies are in the user's language.
_LEAKED_REASONING = re.compile(
    r"^(?=[\x00-\x7f]*$)(?:.*\btool[ _]?calls?\b|(?:we|i) (?:need|should|must|have) to\b"
    r"|let'?s\b|the user (?:wants|asks|says|is asking)\b|need to\b)",
    re.I | re.S,
)


def _final_rule(names: Sequence[str]) -> str:
    """Which tools end the turn: anything the user asked for after them must already be in the reply."""
    if not names:
        return ""
    return (
        f" {', '.join(names)} end your turn as soon as they succeed, and you get no reply after "
        "that. So when the user asks for several things, put every call into this one reply, "
        "in the order they asked."
    )


def _text(message: Any) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part) for part in content
    )


def _reply_language(messages: Sequence[BaseMessage]) -> str:
    """A language reminder for the end of the prompt, once tool results follow the request."""
    read_results = False
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            read_results = True
        # The agent's own notes are HumanMessages too; they start with "[SYSTEM]".
        elif isinstance(msg, HumanMessage) and not _text(msg).startswith("[SYSTEM]"):
            if not read_results:
                return ""
            return _REPLY_THAI if _THAI.search(_text(msg)) else _REPLY_SAME
    return ""


def _call_text(call: dict[str, Any]) -> str:
    payload = {"name": call["name"], "arguments": call.get("args", {})}
    return f"{_OPEN}{json.dumps(payload, ensure_ascii=False)}{_CLOSE}"


def render_messages(
    messages: Sequence[BaseMessage], tools: list[dict], final_tools: Sequence[str] = ()
) -> list[BaseMessage]:
    """Rewrite a tool-calling history into plain system/user/assistant turns."""
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            pairs.append(("system", _text(msg)))
        elif isinstance(msg, AIMessage):
            text = _PROTOCOL.sub("", _text(msg)).strip()
            for call in msg.tool_calls:
                text = f"{text}\n{_call_text(call)}".strip()
            pairs.append(("assistant", text))
        elif isinstance(msg, ToolMessage):
            name = msg.name or "tool"
            pairs.append(("user", f'<tool_response name="{name}">\n{_text(msg)}\n</tool_response>'))
        else:
            pairs.append(("user", _text(msg)))

    reminder = _reply_language(messages)
    if reminder:
        pairs[-1] = (pairs[-1][0], f"{pairs[-1][1]}\n{reminder}")

    if tools:
        section = _TOOL_INSTRUCTIONS.format(
            tools="\n".join(json.dumps(t["function"], ensure_ascii=False) for t in tools),
            max_calls=_MAX_CALLS,
            final=_final_rule(final_tools),
        )
        if pairs and pairs[0][0] == "system":
            pairs[0] = ("system", pairs[0][1] + section)
        else:
            pairs.insert(0, ("system", section.strip()))

    # Some instruct models reject consecutive messages with the same role.
    squashed: list[tuple[str, str]] = []
    for role, content in pairs:
        if squashed and squashed[-1][0] == role:
            squashed[-1] = (role, f"{squashed[-1][1]}\n{content}")
        else:
            squashed.append((role, content))

    kinds = {"system": SystemMessage, "assistant": AIMessage, "user": HumanMessage}
    return [kinds[role](content=content) for role, content in squashed]


def _load_json(raw: str) -> Any:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()).strip()
    try:
        return json.loads(raw)
    except ValueError:
        try:
            return parse_partial_json(raw)
        except Exception:
            return None


def _to_call(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return None

    args = data.get("arguments", data.get("args", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return {"name": data["name"].strip(), "args": args}


def _parse_call(raw: str) -> dict[str, Any] | None:
    """Turn the text between the tags into {"name", "args"}, or None if unusable."""
    return _to_call(_load_json(raw))


def _bare_call(text: str, names: set[str]) -> dict[str, Any] | None:
    """A call written as plain JSON with no tags, ending the reply, for a tool on offer."""
    body = re.sub(r"\s*```\s*$", "", text.strip())
    for brace in re.finditer(r"\{", body):
        try:
            data = json.loads(body[brace.start() :])
        except ValueError:
            continue
        # The first "{" that parses to the end is the outermost object; anything
        # after it would only be a piece of it, such as the arguments.
        call = _to_call(data)
        return call if call is not None and call["name"] in names else None
    return None


def _parse_harmony(raw: str) -> dict[str, Any] | None:
    """Read a call out of a harmony block, or None if it holds no usable call."""
    # The call follows the last recipient; anything before it may be reasoning.
    recipients = list(_HARMONY_RECIPIENT.finditer(raw))
    recipient = recipients[-1] if recipients else None
    brace = raw.find("{", recipient.end() if recipient else 0)
    if brace == -1:
        return None
    token = _HARMONY_TOKEN.search(raw, brace)
    data = _load_json(raw[brace : token.start() if token else len(raw)])
    call = _to_call(data)
    if call is not None or recipient is None or not isinstance(data, dict):
        return call
    # Native harmony names the tool in the recipient and sends only the arguments.
    return _to_call({"name": recipient.group(1).removeprefix("functions."), "arguments": data})


def _harmony_final(raw: str) -> str:
    """The answer in a harmony `final` channel, if the block is one."""
    match = _HARMONY_FINAL.search(raw)
    return _HARMONY_TOKEN.sub("", match.group(1)).strip() if match else ""


def _find_open(buffer: str) -> tuple[int, str | None]:
    """Where the earliest call opener starts, and which kind it is."""
    found = [(buffer.find(_OPEN), "tag"), (buffer.find(_FAKE_RESPONSE), "fake")]
    found += [(buffer.find(token), "harmony") for token in _HARMONY_OPENERS]
    found = [(pos, kind) for pos, kind in found if pos != -1]
    return min(found) if found else (-1, None)


def _partial_open_len(buffer: str) -> int:
    """Length of the longest buffer suffix that could still grow into an opener."""
    openers = (_OPEN, _FAKE_RESPONSE, *_HARMONY_OPENERS)
    for size in range(min(len(buffer), max(map(len, openers)) - 1), 0, -1):
        if any(opener.startswith(buffer[-size:]) for opener in openers):
            return size
    return 0


class ToolPromptChatModel(BaseChatModel):
    """Gives any chat model tool calling by describing the tools in the prompt."""

    inner: BaseChatModel

    @property
    def _llm_type(self) -> str:
        return "tool-prompt-openrouter"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any):
        # `tools` is never forwarded to the provider; _astream turns it into prompt text.
        return self.bind(
            tools=[convert_to_openai_tool(t) for t in tools],
            # The schema drops return_direct, and the model must know about it.
            final_tools=[t.name for t in tools if getattr(t, "return_direct", False)],
            **kwargs,
        )

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("ToolPromptChatModel is async-only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return await agenerate_from_stream(self._astream(messages, stop, run_manager, **kwargs))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        tools = kwargs.pop("tools", None) or []
        final_tools = kwargs.pop("final_tools", None) or []
        kwargs.pop("tool_choice", None)
        kwargs.pop("parallel_tool_calls", None)

        rendered = render_messages(messages, tools, final_tools)
        stream = self.inner.astream(rendered, stop=stop, **kwargs)

        buffer = block = ""
        mode: str | None = None  # "tag", "harmony" or "fake" while one is open
        calls: list[dict[str, Any]] = []
        # Text before a call is dropped (see _PREAMBLE_CHARS), so the start of a
        # reply is held until it is long enough to be an answer.
        held, holding = "", True
        done = False

        async def emit(text: str):
            if run_manager:
                await run_manager.on_llm_new_token(text)
            return ChatGenerationChunk(message=AIMessageChunk(content=text))

        try:
            async for piece in stream:
                buffer += _text(piece)

                # One piece can close a call and open the next.
                while not done:
                    if mode is None:
                        start, mode = _find_open(buffer)
                        if mode is None:
                            keep = _partial_open_len(buffer)
                            out, buffer = buffer[: len(buffer) - keep], buffer[len(buffer) - keep :]
                        else:
                            out = buffer[:start]
                            # Harmony keeps its tokens: the recipient sits between them.
                            buffer = buffer[start + len(_OPEN) :] if mode == "tag" else buffer[start:]

                        if calls:
                            out = ""  # between or after calls: not part of an answer
                        elif holding:
                            held += out
                            if len(held) > _PREAMBLE_CHARS:
                                out, held, holding = held, "", False
                            else:
                                out = ""
                        if out:
                            yield await emit(out)
                        if mode is None:
                            break
                        if mode == "fake":
                            done = True
                            break

                    close = _CLOSE if mode == "tag" else _HARMONY_CALL
                    end = buffer.find(close)
                    if end == -1:
                        break
                    block, buffer = buffer[:end], buffer[end + len(close) :]
                    if mode == "harmony":
                        done = True  # harmony ends the message at its call
                        break
                    call = _parse_call(block)
                    if call is None:
                        logger.warning(f"[Tools] Dropped unreadable tool call: {block[:200]!r}")
                    else:
                        calls.append(call)
                    mode = None
                    if len(calls) == _MAX_CALLS:
                        done = True
                if done:
                    break
            else:
                block = buffer
        except ValueError as exc:
            # LangChain raises this when the stream carried no data at all: OpenRouter
            # answered 200 and closed it empty (seen on the free endpoint). Treat it as
            # an empty reply.
            if "No generation chunks" not in str(exc):
                raise
            block = buffer
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        tail = ""
        if mode == "tag" and block.strip():
            # An unclosed tag means the model stopped early; its JSON may still be whole.
            call = _parse_call(block)
            if call is None:
                logger.warning(f"[Tools] Dropped unreadable tool call: {block[:200]!r}")
            else:
                calls.append(call)
        elif mode == "harmony":
            call = _parse_harmony(block)
            if call is not None:
                calls.append(call)
            elif not calls:
                tail = _harmony_final(block)
                if not tail:
                    logger.warning(f"[Tools] Dropped harmony block: {block[:200]!r}")
        elif mode is None and not calls:
            tail = buffer
            # gpt-oss sometimes drops the tags and writes the bare JSON. Only a short
            # reply (still held, nothing shown) naming a real tool counts as a call.
            if holding and tools:
                call = _bare_call(held + tail, {t["function"]["name"] for t in tools})
                if call is not None:
                    calls.append(call)

        # A <tool_response> written after real calls is just cut off: the calls run
        # and their real results replace it.
        fabricated = mode == "fake" and not calls
        if calls or fabricated:
            if held.strip():
                logger.debug(f"[Tools] Dropped text before a call: {held[:200]!r}")
        elif held + tail and holding and tools and _LEAKED_REASONING.match((held + tail).strip()):
            # Sent as an empty reply, which the agent retries once.
            logger.warning(f"[Tools] Reasoning without a call; dropped: {(held + tail)[:200]!r}")
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))
        elif held + tail:
            yield await emit(held + tail)
        elif holding:
            # Nothing usable came back: an empty stream, or only an unreadable call.
            # LangChain rejects a stream with no chunks, so send an empty one and let
            # the agent decide.
            logger.warning(f"[Tools] Model returned no usable reply: {block[:200]!r}")
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))

        if fabricated:
            logger.warning("[Tools] Model wrote its own tool response; cut it off")
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", additional_kwargs={FABRICATED: True})
            )

        if calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"], ensure_ascii=False),
                            "id": uuid.uuid4().hex,
                            "index": index,
                        }
                        for index, call in enumerate(calls)
                    ],
                )
            )
