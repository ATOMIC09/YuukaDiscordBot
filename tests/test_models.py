"""Azure OpenAI as the provider, OpenRouter as the fallback."""

import dataclasses

import openai
import pytest
from langchain_core.messages import HumanMessage

from bot.config import Config, azure_base_url
from tests.fakes import Flaky, api_error
from utils.ai import agent, models
from utils.ai.agent import run_agent
from utils.ai.context import YuukaContext
from utils.ai.models import ContentFiltered, FailoverChat, Provider, filter_categories


# ── Settings ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "given",
    [
        "https://res.openai.azure.com",
        "https://res.openai.azure.com/",
        "https://res.openai.azure.com/openai",
        "https://res.openai.azure.com/openai/v1",
        "https://res.openai.azure.com/openai/v1/",
        "https://res.openai.azure.com/openai/v1/chat/completions",
        "  https://res.openai.azure.com/openai/v1/chat/completions/  ",
    ],
)
def test_azure_endpoint_is_normalised_to_the_v1_base(given):
    assert azure_base_url(given) == "https://res.openai.azure.com/openai/v1/"


AZURE = {
    "AZURE_OPENAI_ENDPOINT": "https://res.openai.azure.com/openai/v1/chat/completions",
    "AZURE_OPENAI_API_KEY": "azure-key",
    "AZURE_OPENAI_DEPLOYMENT": "my-deployment",
}


def settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Config.from_env()


def test_default_is_openrouter_alone(monkeypatch):
    cfg = settings(monkeypatch)
    assert (cfg.llm_provider, cfg.llm_fallback) == ("openrouter", "")


def test_azure_with_openrouter_fallback(monkeypatch):
    cfg = settings(monkeypatch, LLM_PROVIDER="azure", LLM_FALLBACK="openrouter", **AZURE)
    assert (cfg.llm_provider, cfg.llm_fallback) == ("azure", "openrouter")
    assert cfg.azure_openai_base_url == "https://res.openai.azure.com/openai/v1/"
    assert cfg.azure_openai_deployment == "my-deployment"


def test_openrouter_key_is_only_needed_when_openrouter_is_used(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert settings(monkeypatch, LLM_PROVIDER="azure", **AZURE).llm_provider == "azure"
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        settings(monkeypatch, LLM_PROVIDER="azure", LLM_FALLBACK="openrouter", **AZURE)


@pytest.mark.parametrize("missing", list(AZURE))
def test_azure_needs_all_three_settings(monkeypatch, missing):
    with pytest.raises(ValueError, match=missing):
        settings(monkeypatch, LLM_PROVIDER="azure", **{**AZURE, missing: ""})


@pytest.mark.parametrize(
    "env",
    [{"LLM_PROVIDER": "gpt"}, {"LLM_FALLBACK": "gpt"}, {"LLM_PROVIDER": "openrouter", "LLM_FALLBACK": "openrouter"}],
)
def test_bad_provider_settings_are_refused(monkeypatch, env):
    with pytest.raises(ValueError, match="LLM_"):
        settings(monkeypatch, **env)


# ── Failing over ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def forget_pauses():
    models._paused_until.clear()
    yield
    models._paused_until.clear()


def failover(*chats: tuple[str, Flaky]) -> FailoverChat:
    return FailoverChat(providers=[Provider(name, f"{name}-model", lambda chat=chat: chat) for name, chat in chats])


async def ask(chat: FailoverChat) -> str:
    return "".join([c.content async for c in chat.astream([HumanMessage(content="hi")])])


async def test_primary_answers_when_it_works():
    azure, router = Flaky(replies=["จาก azure"]), Flaky(replies=["จาก openrouter"])
    chat = failover(("azure", azure), ("openrouter", router))
    assert await ask(chat) == "จาก azure"
    assert chat.last_provider == "azure/azure-model"
    assert router.seen == []


@pytest.mark.parametrize(
    "error",
    [
        api_error(openai.RateLimitError, 429),
        api_error(openai.InternalServerError, 503),
        api_error(openai.AuthenticationError, 401),
        api_error(openai.NotFoundError, 404),
        openai.APIConnectionError(request=None),
    ],
)
async def test_failure_before_the_first_chunk_moves_to_the_fallback(error):
    azure = Flaky(replies=[], error=error)
    chat = failover(("azure", azure), ("openrouter", Flaky(replies=["จาก openrouter"])))
    assert await ask(chat) == "จาก openrouter"
    assert chat.last_provider == "openrouter/openrouter-model"


async def test_a_failed_provider_is_skipped_for_a_while():
    azure = Flaky(replies=[], error=api_error(openai.RateLimitError, 429))
    router = Flaky(replies=["หนึ่ง", "สอง"])
    assert await ask(failover(("azure", azure), ("openrouter", router))) == "หนึ่ง"
    assert await ask(failover(("azure", azure), ("openrouter", router))) == "สอง"
    assert len(azure.seen) == 1  # the second turn did not try it again


async def test_when_every_provider_is_paused_they_are_tried_in_order():
    models._paused_until.update({"azure": 1e12, "openrouter": 1e12})
    azure = Flaky(replies=["จาก azure"])
    assert await ask(failover(("azure", azure), ("openrouter", Flaky(replies=[])))) == "จาก azure"


async def test_never_switches_after_a_chunk_has_arrived():
    azure = Flaky(replies=["ครึ่งประโยค"], piece=3, error=api_error(openai.InternalServerError, 500), after=1)
    router = Flaky(replies=["จาก openrouter"])
    chat = failover(("azure", azure), ("openrouter", router))
    with pytest.raises(openai.InternalServerError):
        await ask(chat)
    assert router.seen == []


async def test_last_provider_failing_raises_with_its_name():
    chat = failover(("azure", Flaky(replies=[], error=api_error(openai.RateLimitError, 429))))
    with pytest.raises(openai.RateLimitError) as raised:
        await ask(chat)
    assert raised.value.provider == "Azure OpenAI"


async def test_a_rejected_request_is_not_retried_elsewhere():
    azure = Flaky(replies=[], error=api_error(openai.BadRequestError, 400, code="invalid_prompt"))
    router = Flaky(replies=["จาก openrouter"])
    with pytest.raises(openai.BadRequestError):
        await ask(failover(("azure", azure), ("openrouter", router)))
    assert router.seen == []


async def test_blocked_prompt_is_a_content_filter_and_never_retried_elsewhere():
    azure = Flaky(replies=[], error=api_error(openai.BadRequestError, 400, code="content_filter"))
    router = Flaky(replies=["จาก openrouter"])
    with pytest.raises(ContentFiltered) as raised:
        await ask(failover(("azure", azure), ("openrouter", router)))
    assert raised.value.provider == "Azure OpenAI"
    assert router.seen == []
    assert "azure" not in models._paused_until  # a blocked prompt is not a sick provider


async def test_reply_cut_by_the_filter_is_a_content_filter():
    azure = Flaky(replies=["คำตอบที่ถูกตัด"], finish_reason="content_filter")
    router = Flaky(replies=["จาก openrouter"])
    with pytest.raises(ContentFiltered):
        await ask(failover(("azure", azure), ("openrouter", router)))
    assert router.seen == []


# ── Through the agent ─────────────────────────────────────────────────────

HISTORY = [{"role": "system", "content": "You are Yuuka."}, {"role": "user", "content": "สวัสดี"}]
CTX = YuukaContext(bot=None, guild=None, requester=None, channel=None)


async def events_of(chat) -> list:
    return [e async for e in run_agent(list(HISTORY), CTX, tools=[], model=chat)]


async def test_agent_answers_from_the_fallback_when_the_primary_is_down():
    chat = failover(
        ("azure", Flaky(replies=[], error=api_error(openai.RateLimitError, 429))),
        ("openrouter", Flaky(replies=["สวัสดีค่ะ เซนเซย์"])),
    )
    events = await events_of(chat)
    assert "".join(p for k, p in events if k == "content") == "สวัสดีค่ะ เซนเซย์"
    assert not [e for e in events if e[0] == "error"]


async def test_agent_reports_a_content_filter_in_persona():
    chat = failover(("azure", Flaky(replies=[], error=api_error(openai.BadRequestError, 400, code="content_filter"))))
    ((_, payload),) = [e for e in await events_of(chat) if e[0] == "error"]
    assert payload["user"] == agent._FILTERED_REPLY
    assert "Azure OpenAI" in payload["dev"]


async def test_agent_names_the_provider_that_failed():
    chat = failover(("azure", Flaky(replies=[], error=api_error(openai.AuthenticationError, 401))))
    ((_, payload),) = [e for e in await events_of(chat) if e[0] == "error"]
    assert "Azure OpenAI returned status 401" in payload["user"]


# ── Building the providers ────────────────────────────────────────────────

def configured(monkeypatch, **fields):
    monkeypatch.setattr(models, "config", dataclasses.replace(models.config, **fields))


def test_providers_follow_the_settings(monkeypatch):
    configured(
        monkeypatch,
        llm_provider="azure",
        llm_fallback="openrouter",
        azure_openai_base_url="https://res.openai.azure.com/openai/v1/",
        azure_openai_api_key="azure-key",
        azure_openai_deployment="my-deployment",
    )
    azure, router = models.providers()
    assert (azure.name, azure.model) == ("azure", "my-deployment")
    assert router.name == "openrouter"
    client = azure.build()
    assert client.model_name == "my-deployment"
    assert client.openai_api_base == "https://res.openai.azure.com/openai/v1/"
    assert client.max_tokens == models.config.openrouter_max_tokens
    assert not client.extra_body  # OpenRouter's own token field is not sent to Azure
    assert client.max_retries == 0  # a fallback is waiting; the client's own retries would only delay it


def test_a_lone_provider_keeps_the_client_retry(monkeypatch):
    configured(monkeypatch, llm_provider="openrouter", llm_fallback="")
    (only,) = models.providers()
    assert only.build().max_retries == 1


def test_disclosure_names_the_primary_and_its_fallback(monkeypatch):
    configured(monkeypatch, llm_provider="azure", llm_fallback="openrouter", azure_openai_deployment="my-deployment")
    assert models.disclosure() == {"model": "my-deployment", "provider": "azure", "fallback": "openrouter"}


# ── Which filter fired ────────────────────────────────────────────────────

AZURE_BODY = {
    "message": "The response was filtered due to the prompt triggering Azure OpenAI's content management policy.",
    "param": "prompt",
    "code": "content_filter",
    "innererror": {
        "code": "ResponsibleAIPolicyViolation",
        "content_filter_result": {
            "hate": {"filtered": False, "severity": "safe"},
            "jailbreak": {"filtered": True, "detected": True},
            "violence": {"filtered": True, "severity": "medium"},
        },
    },
}


def test_the_categories_that_fired_are_named_without_the_words():
    exc = api_error(openai.BadRequestError, 400, **AZURE_BODY)
    assert filter_categories(exc) == ["jailbreak", "violence (medium)"]
    assert filter_categories(api_error(openai.BadRequestError, 400, error=AZURE_BODY)) == ["jailbreak", "violence (medium)"]


def test_a_body_without_categories_names_none():
    assert filter_categories(api_error(openai.BadRequestError, 400, code="content_filter")) == []
    assert filter_categories(ValueError("no body")) == []


async def test_the_blocked_request_names_the_category_in_the_error():
    azure = Flaky(replies=[], error=api_error(openai.BadRequestError, 400, **AZURE_BODY))
    ((_, payload),) = [e for e in await events_of(failover(("azure", azure))) if e[0] == "error"]
    assert "jailbreak" in payload["dev"] and payload["user"] == agent._FILTERED_REPLY
