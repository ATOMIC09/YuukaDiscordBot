"""
utils/ai/models.py
The chat model: Azure OpenAI and/or OpenRouter, in the order `LLM_PROVIDER` / `LLM_FALLBACK` say.

`chat_model()` returns one model that tries the providers in turn. A request that fails *before its
first chunk* with a rate limit, a timeout, an outage or a rejected key moves on to the next provider
(and the failed one is skipped for a while). After a chunk has arrived it never switches: text may
already be posted or spoken. A content-filter block is never retried elsewhere, since that would
route around a safety control.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

import openai
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from bot.config import config
from bot.logger import logger

_OPENROUTER_URL = "https://openrouter.ai/api/v1"

LABELS = {"azure": "Azure OpenAI", "openrouter": "OpenRouter"}

# How long a provider that failed is skipped, in seconds. RAM only.
_PAUSE_RATE_LIMIT_S = 60
_PAUSE_DOWN_S = 300
_paused_until: dict[str, float] = {}


class ContentFiltered(Exception):
    """The provider's content filter blocked the prompt or cut the reply."""

    provider = ""


@dataclass(frozen=True)
class Provider:
    name: str  # "azure" | "openrouter"
    model: str  # the Azure deployment, or the OpenRouter model id
    build: Callable[[], BaseChatModel]

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)


def _openrouter(retries: int) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.openrouter_model,
        base_url=_OPENROUTER_URL,
        api_key=config.openrouter_api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/ATOMIC09/YuukaDiscordBot",
            "X-Title": "Yuuka-Bot",
        },
        # OpenRouter's own field. langchain's `max_tokens` is sent as `max_completion_tokens`.
        extra_body={"max_tokens": config.openrouter_max_tokens},
        # Asks OpenRouter for the token counts that `tool_calling` logs as [Usage].
        stream_usage=True,
        timeout=180,
        max_retries=retries,
    )


def _azure(retries: int) -> ChatOpenAI:
    # The v1 API takes the plain OpenAI client: no api-version, and `model` is the deployment name.
    return ChatOpenAI(
        model=config.azure_openai_deployment,
        base_url=config.azure_openai_base_url,
        api_key=config.azure_openai_api_key,
        max_tokens=config.openrouter_max_tokens,
        stream_usage=True,
        timeout=180,
        max_retries=retries,
    )


def providers() -> list[Provider]:
    """The configured providers, primary first."""
    names = [config.llm_provider] + ([config.llm_fallback] if config.llm_fallback else [])
    # With a fallback waiting, the client's own retries would only delay the switch.
    retries = 0 if len(names) > 1 else 1
    models = {
        "azure": (config.azure_openai_deployment, lambda: _azure(retries)),
        "openrouter": (config.openrouter_model, lambda: _openrouter(retries)),
    }
    return [Provider(name, *models[name]) for name in names]


def disclosure() -> dict[str, str]:
    """What the session-start embed tells members about who answers."""
    primary, *rest = providers()
    return {
        "model": primary.model,
        "provider": primary.name,
        "fallback": rest[0].name if rest else "",
    }


# ── Failing over ──────────────────────────────────────────────────────────

def _switchable(exc: Exception) -> bool:
    """Whether another provider may answer instead: it is busy, down or misconfigured. A rejected
    request (400) is not: the content filter in particular must not be routed around."""
    return isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.APIConnectionError,  # includes timeouts
            openai.InternalServerError,
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ),
    )


def _is_content_filter(exc: Exception) -> bool:
    return isinstance(exc, openai.BadRequestError) and getattr(exc, "code", None) == "content_filter"


def _available(candidates: list[Provider]) -> list[Provider]:
    now = time.monotonic()
    ready = [p for p in candidates if _paused_until.get(p.name, 0) <= now]
    # All paused: try them anyway, in order, rather than answer nothing.
    return ready or candidates


def _pause(provider: Provider, exc: Exception) -> None:
    seconds = _PAUSE_RATE_LIMIT_S if isinstance(exc, openai.RateLimitError) else _PAUSE_DOWN_S
    _paused_until[provider.name] = time.monotonic() + seconds


class FailoverChat(BaseChatModel):
    """One chat model over several providers (see the module docstring)."""

    providers: list[Provider]
    # Which provider answered the last request, for the [Usage] line.
    last_provider: str = ""

    @property
    def _llm_type(self) -> str:
        return "failover"

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("FailoverChat is async-only")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        candidates = _available(self.providers)
        for position, provider in enumerate(candidates):
            has_next = position < len(candidates) - 1
            started = False
            filtered = False
            self.last_provider = f"{provider.name}/{provider.model}"
            try:
                async for chunk in provider.build().astream(messages, stop=stop, **kwargs):
                    started = True
                    if chunk.response_metadata.get("finish_reason") == "content_filter":
                        filtered = True
                    yield ChatGenerationChunk(message=chunk)
            except Exception as exc:
                exc.provider = provider.label  # type: ignore[attr-defined]
                if _is_content_filter(exc):
                    raise _filtered(provider, filter_categories(exc)) from exc
                if started or not _switchable(exc):
                    raise
                _pause(provider, exc)
                if not has_next:
                    raise
                status = getattr(exc, "status_code", None) or type(exc).__name__
                paused = int(_paused_until[provider.name] - time.monotonic())
                logger.warning(
                    f"[LLM] {provider.name} → {candidates[position + 1].name} ({status}), "
                    f"{provider.name} paused {paused}s"
                )
                continue
            if filtered:
                raise _filtered(provider)
            return


def filter_categories(exc: Exception) -> list[str]:
    """Which of Azure's filters fired (hate, violence, jailbreak…), from the 400's body. Category
    names only: the body says what kind of thing was found, never the words."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return []
    body = body.get("error") if isinstance(body.get("error"), dict) else body
    inner = body.get("innererror") if isinstance(body.get("innererror"), dict) else {}
    results = inner.get("content_filter_result")
    if not isinstance(results, dict):
        return []
    found = []
    for category, result in results.items():
        if isinstance(result, dict) and result.get("filtered"):
            severity = result.get("severity")
            found.append(f"{category} ({severity})" if severity else category)
    return found


def _filtered(provider: Provider, categories: list[str] | None = None) -> ContentFiltered:
    # Counted, never quoted: what was blocked is a member's words. Which filter fired is not.
    detail = f": {', '.join(categories)}" if categories else ""
    logger.warning(f"[LLM] {provider.label} content filter blocked a request{detail}")
    exc = ContentFiltered(f"{provider.label} content filter{detail}")
    exc.provider = provider.label
    return exc


def chat_model() -> FailoverChat:
    """A streaming-capable client over the configured providers."""
    return FailoverChat(providers=providers())
