"""
tests/fakes.py
A scripted chat model: each model call answers with the next string, streamed in small pieces
so a tag or token can be split across chunks the way a real provider splits it.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field


class ScriptedChat(BaseChatModel):
    replies: list[str]
    piece: int = 5
    # What each call was sent, for tests that check the prompt.
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self.seen.append(list(messages))
        if not self.replies:
            raise AssertionError("the model was called more often than the test scripted")
        text = self.replies.pop(0)
        if not text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))
            return
        for start in range(0, len(text), self.piece):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text[start : start + self.piece]))


class Flaky(ScriptedChat):
    """A provider that raises `error` once it has sent `after` chunks (0 = before the first)."""

    error: Exception | None = None
    after: int = 0
    finish_reason: str = ""

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        if self.error is not None and self.after == 0:
            raise self.error
        text = self.replies.pop(0) if self.replies else ""
        pieces = [text[i : i + self.piece] for i in range(0, len(text), self.piece)] or [""]
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            meta = {"finish_reason": self.finish_reason} if last and self.finish_reason else {}
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece, response_metadata=meta))
            if self.error is not None and index + 1 == self.after:
                raise self.error


def api_error(kind: type, status: int, **body: Any) -> Exception:
    """An `openai` exception of the given class, built the way the client builds it."""
    import httpx

    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid/v1/chat"))
    return kind("provider said no", response=response, body=body or None)


def call(name: str, **arguments: Any) -> str:
    """A tool call as the model writes it."""
    import json

    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False)}</tool_call>"
