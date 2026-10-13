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


def call(name: str, **arguments: Any) -> str:
    """A tool call as the model writes it."""
    import json

    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False)}</tool_call>"
