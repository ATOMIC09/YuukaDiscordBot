"""
utils/ai/tool_calling.py
Tool calling for a chat model that has no native tool-call support.

The free OpenRouter model Yuuka runs on rejects the `tools` parameter, so tools
are described to it in the prompt and it answers in plain text:

    <tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>

`ToolPromptChatModel` wraps any chat model and turns that text back into a
standard `AIMessage.tool_calls`, so everything above it (tools, the agent loop)
is ordinary LangChain and would work unchanged on a model with native tools.

Call text is never yielded as content: it must not reach Discord or TTS.
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

_TOOL_INSTRUCTIONS = """

[TOOLS]
You can use tools. Available tools (JSON schema for each):
{tools}

To use a tool, reply with ONE short sentence in your normal voice, then the call, then nothing at all:
<tool_call>{{"name": "<tool name>", "arguments": {{...}}}}</tool_call>

The result comes back as a message of the form <tool_response name="...">...</tool_response>.
Use it to answer the user, or call another tool if you still need something.

Rules:
- Only use a tool when the user clearly asks for it or you truly need it. Talking about something is not the same as asking for it.
- At most ONE call per reply, and it must be the last thing you write.
- Never describe the call format or mention that you are using tools.
- Never invent arguments the user did not give and no earlier tool result provided."""


def _text(message: Any) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part) for part in content
    )


def _call_text(call: dict[str, Any]) -> str:
    payload = {"name": call["name"], "arguments": call.get("args", {})}
    return f"{_OPEN}{json.dumps(payload, ensure_ascii=False)}{_CLOSE}"


def render_messages(messages: Sequence[BaseMessage], tools: list[dict]) -> list[BaseMessage]:
    """Rewrite a tool-calling history into plain system/user/assistant turns."""
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            pairs.append(("system", _text(msg)))
        elif isinstance(msg, AIMessage):
            text = _text(msg)
            for call in msg.tool_calls:
                text = f"{text}\n{_call_text(call)}".strip()
            pairs.append(("assistant", text))
        elif isinstance(msg, ToolMessage):
            name = msg.name or "tool"
            pairs.append(("user", f'<tool_response name="{name}">\n{_text(msg)}\n</tool_response>'))
        else:
            pairs.append(("user", _text(msg)))

    if tools:
        section = _TOOL_INSTRUCTIONS.format(
            tools="\n".join(json.dumps(t["function"], ensure_ascii=False) for t in tools)
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


def _parse_call(raw: str) -> dict[str, Any] | None:
    """Turn the text between the tags into {"name", "args"}, or None if unusable."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        try:
            data = parse_partial_json(raw)
        except Exception:
            return None
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


def _partial_open_len(buffer: str) -> int:
    """Length of the longest buffer suffix that could still grow into the open tag."""
    for size in range(min(len(buffer), len(_OPEN) - 1), 0, -1):
        if _OPEN.startswith(buffer[-size:]):
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
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

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
        kwargs.pop("tool_choice", None)
        kwargs.pop("parallel_tool_calls", None)

        rendered = render_messages(messages, tools)
        stream = self.inner.astream(rendered, stop=stop, **kwargs)

        buffer = ""
        in_call = False
        call: dict[str, Any] | None = None

        async def emit(text: str):
            if run_manager:
                await run_manager.on_llm_new_token(text)
            return ChatGenerationChunk(message=AIMessageChunk(content=text))

        try:
            async for piece in stream:
                buffer += _text(piece)

                if not in_call:
                    start = buffer.find(_OPEN)
                    if start == -1:
                        keep = _partial_open_len(buffer)
                        out, buffer = buffer[: len(buffer) - keep], buffer[len(buffer) - keep :]
                        if out:
                            yield await emit(out)
                        continue
                    out, buffer, in_call = buffer[:start], buffer[start + len(_OPEN) :], True
                    if out:
                        yield await emit(out)

                end = buffer.find(_CLOSE)
                if end != -1:
                    call = _parse_call(buffer[:end])
                    if call is None:
                        logger.warning(f"[Tools] Dropped unreadable tool call: {buffer[:end][:200]!r}")
                    buffer = ""
                    in_call = False
                    break
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        if in_call and buffer.strip():
            # The model stopped before closing the tag; its JSON may still be whole.
            call = _parse_call(buffer)
            if call is None:
                logger.warning(f"[Tools] Dropped unterminated tool call: {buffer[:200]!r}")
        elif not in_call and call is None and buffer:
            yield await emit(buffer)

        if call is not None:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"], ensure_ascii=False),
                            "id": uuid.uuid4().hex,
                            "index": 0,
                        }
                    ],
                )
            )
