"""Tokens and time per model call, the totals behind /status, and the usage channel."""

import asyncio
import dataclasses

import openai
from langchain_core.messages import HumanMessage

from tests.fakes import Flaky, ScriptedChat, api_error
from utils.ai import usage
from utils.ai.agent import run_agent
from utils.ai.context import YuukaContext
from utils.ai.models import FailoverChat, Provider
from utils.ai.tool_calling import ToolPromptChatModel
from utils.ai.usage import CallUsage

TOKENS = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150, "output_token_details": {"reasoning": 7}}


async def drain(model):
    return [chunk async for chunk in model.astream([HumanMessage(content="hi")])]


# ── Per call ──────────────────────────────────────────────────────────────

async def test_a_call_records_its_tokens():
    model = ToolPromptChatModel(inner=ScriptedChat(replies=["ตอบแล้วค่ะ"], usage=TOKENS))
    await drain(model)
    (call,) = model.usage_log
    assert (call.prompt, call.reply, call.reasoning) == (120, 30, 7)


async def test_a_provider_that_reports_no_tokens_still_records_the_call():
    model = ToolPromptChatModel(inner=ScriptedChat(replies=["ตอบแล้วค่ะ"]))
    await drain(model)
    (call,) = model.usage_log
    assert call.prompt is None and call.reply is None and call.seconds >= 0


async def test_time_is_the_providers_wait_not_the_consumers():
    # A 400-character answer streams in 20 chunks; the provider takes 30 ms before each and the
    # consumer 50 ms over each, which is what a Discord edit costs.
    model = ToolPromptChatModel(inner=ScriptedChat(replies=["ก" * 400], piece=20, delay=0.03))
    async for _ in model.astream([HumanMessage(content="hi")]):
        await asyncio.sleep(0.05)
    (call,) = model.usage_log
    assert 0.03 * 20 * 0.8 <= call.seconds < 0.03 * 20 + 0.25  # not the ~1.6 s the pair spent
    assert 0.025 <= call.first_chunk < 0.15


async def test_every_round_of_a_turn_is_one_call():
    model = ToolPromptChatModel(inner=ScriptedChat(replies=["หนึ่ง", "สอง"]))
    await drain(model)
    await drain(model)
    assert len(model.usage_log) == 2


async def test_the_provider_that_answered_is_recorded():
    chat = FailoverChat(providers=[Provider("azure", "m", lambda: ScriptedChat(replies=["ค่ะ"], usage=TOKENS))])
    model = ToolPromptChatModel(inner=chat)
    await drain(model)
    assert model.usage_log[0].provider == "azure/m"


async def test_a_switch_to_the_fallback_is_counted():
    chat = FailoverChat(
        providers=[
            Provider("azure", "m", lambda: Flaky(replies=[], error=api_error(openai.RateLimitError, 429))),
            Provider("openrouter", "n", lambda: ScriptedChat(replies=["ค่ะ"])),
        ]
    )
    await drain(ToolPromptChatModel(inner=chat))
    assert chat.fallbacks == 1 and chat.last_provider == "openrouter/n"


# ── Totals and the embed ──────────────────────────────────────────────────

def call(provider="azure/m", prompt=100, reply=20, reasoning=5, seconds=1.0, first=0.4):
    return CallUsage(provider, prompt, reply, reasoning, seconds, first)


def test_nothing_asked_means_no_summary():
    assert usage.summary() == ""


def test_totals_add_up_per_provider():
    usage.record_turn([call(seconds=1.0), call(seconds=3.0)])
    usage.record_turn([call("openrouter/n", prompt=50, reply=10, seconds=2.0)], fallbacks=1)
    text = usage.summary()
    assert "คำตอบ: `2`" in text and "`1` ครั้ง" in text
    assert "`azure/m`: 2 คำขอ, token 200 เข้า / 40 ออก (คิด 10), เฉลี่ย 2.0s, ช้าสุด 3.0s" in text
    assert "`openrouter/n`: 1 คำขอ, token 50 เข้า / 10 ออก" in text


def test_a_call_without_token_counts_adds_nothing_to_them():
    usage.record_turn([CallUsage("azure/m", None, None, 0, 1.0, None)])
    assert "token 0 เข้า / 0 ออก" in usage.summary()


def test_the_embed_sums_the_turn_and_holds_no_text():
    embed = usage.turn_embed([call(), call(prompt=40, reply=10, reasoning=0, seconds=2.0)], fallbacks=0, voice=True)
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Token"] == "`140` เข้า / `30` ออก (คิด `5`)"
    assert fields["เวลารอโมเดล"] == "`3.00s`" and fields["ช่องทาง"] == "เสียง"
    assert "สลับไปสำรอง" not in fields["โมเดล"]
    assert usage.turn_embed([call()], fallbacks=1, voice=False).fields[0].value.endswith("(สลับไปสำรอง)")


# ── Posting ───────────────────────────────────────────────────────────────

class FakeChannel:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, embed):
        if self.fail:
            raise RuntimeError("Missing Access")
        self.sent.append(embed)


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel


def with_channel(monkeypatch, channel_id=123):
    monkeypatch.setattr(usage, "config", dataclasses.replace(usage.config, usage_channel_id=channel_id))


async def test_a_turn_is_posted_to_the_usage_channel(monkeypatch):
    with_channel(monkeypatch)
    channel = FakeChannel()
    usage.finish_turn(FakeBot(channel), [call()], 0, False)
    await asyncio.gather(*usage._tasks)
    assert len(channel.sent) == 1
    assert "Token" in [f.name for f in channel.sent[0].fields]


async def test_nothing_is_posted_without_a_channel_or_calls(monkeypatch):
    channel = FakeChannel()
    with_channel(monkeypatch, None)
    usage.finish_turn(FakeBot(channel), [call()], 0, False)
    with_channel(monkeypatch, 123)
    usage.finish_turn(FakeBot(channel), [], 0, False)
    usage.finish_turn(None, [call()], 0, False)
    await asyncio.gather(*usage._tasks)
    assert channel.sent == []


async def test_a_channel_that_refuses_does_not_raise(monkeypatch):
    with_channel(monkeypatch)
    usage.finish_turn(FakeBot(FakeChannel(fail=True)), [call()], 0, False)
    await asyncio.gather(*usage._tasks)  # no exception


async def test_a_missing_channel_is_ignored(monkeypatch):
    with_channel(monkeypatch)
    usage.finish_turn(FakeBot(None), [call()], 0, False)
    await asyncio.gather(*usage._tasks)


# ── Through the agent ─────────────────────────────────────────────────────

HISTORY = [{"role": "system", "content": "You are Yuuka."}, {"role": "user", "content": "สวัสดี"}]


async def test_a_turn_through_the_agent_is_counted_and_posted(monkeypatch):
    with_channel(monkeypatch)
    channel = FakeChannel()
    ctx = YuukaContext(bot=FakeBot(channel), guild=None, requester=None, channel=None)
    model = ScriptedChat(replies=["สวัสดีค่ะ"], usage=TOKENS)
    _ = [e async for e in run_agent(list(HISTORY), ctx, tools=[], model=model)]
    await asyncio.gather(*usage._tasks)
    assert "คำตอบ: `1`" in usage.summary()
    assert len(channel.sent) == 1


async def test_a_failed_turn_is_still_counted():
    ctx = YuukaContext(bot=None, guild=None, requester=None, channel=None)
    model = Flaky(replies=["ครึ่งประโยค"], piece=3, error=api_error(openai.InternalServerError, 500), after=1)
    events = [e async for e in run_agent(list(HISTORY), ctx, tools=[], model=model)]
    assert events[-1][0] == "error"
    assert "คำตอบ: `1`" in usage.summary()


# ── The timeline in the embed ─────────────────────────────────────────────

from langchain_core.tools import tool  # noqa: E402

from tests.fakes import call as tool_call  # noqa: E402
from tests.test_agent import tools_that_record  # noqa: E402
from utils.ai.context import Ctx  # noqa: E402
from utils.ai.usage import Step  # noqa: E402


def test_the_timeline_puts_each_tool_under_the_round_that_chose_it():
    calls = [call(seconds=1.2, prompt=300, reply=20), call(seconds=0.8, prompt=420, reply=60)]
    steps = [
        Step(1, "web_search", "ok", 0.8),
        Step(1, "read_messages", "failed", 0.1),
        Step(1, "music_play", "skipped", 0.0),
    ]
    lines = usage.timeline(calls, steps).split("\n")
    assert lines[0] == "**รอบ 1** • `azure/m` • 1.20s • 300 เข้า / 20 ออก"
    assert lines[1] == "　✅ `web_search` 0.80s"
    assert lines[2] == "　❌ `read_messages` 0.10s"
    assert lines[3] == "　⏭️ `music_play`"  # skipped: it never ran, so no time
    assert lines[4].startswith("**รอบ 2**")


def test_a_very_long_turn_is_cut_to_fit_an_embed():
    steps = [Step(1, "web_search", "ok", 0.5) for _ in range(400)]
    text = usage.timeline([call()], steps)
    assert len(text) <= 3810 and text.endswith("…")
    assert len(usage.turn_embed([call()], 0, False, steps).description) <= 4096


async def embed_of_a_turn(monkeypatch, replies, tools):
    with_channel(monkeypatch)
    channel = FakeChannel()
    ctx = YuukaContext(bot=FakeBot(channel), guild=None, requester=None, channel=None)
    model = ScriptedChat(replies=replies, usage=TOKENS)
    _ = [e async for e in run_agent(list(HISTORY), ctx, tools=tools, model=model)]
    await asyncio.gather(*usage._tasks)
    (embed,) = channel.sent
    return embed.description


async def test_the_channel_shows_the_rounds_and_tool_calls_of_a_turn(monkeypatch):
    text = await embed_of_a_turn(monkeypatch, [tool_call("lookup", query="x"), "เจอแล้วค่ะ"], tools_that_record([]))
    assert "**รอบ 1**" in text and "**รอบ 2**" in text
    assert "✅ `lookup`" in text
    assert text.index("lookup") < text.index("**รอบ 2**")  # the call sits under round 1


async def test_a_failed_call_and_the_ones_skipped_after_it_are_marked(monkeypatch):
    text = await embed_of_a_turn(monkeypatch, [tool_call("boom") + tool_call("after"), "ทำไม่ได้ค่ะ"], tools_that_record([]))
    assert "❌ `boom`" in text and "⏭️ `after`" in text


async def test_a_repeated_read_is_marked_skipped(monkeypatch):
    text = await embed_of_a_turn(monkeypatch, [tool_call("web_search", query="x") * 2, "สรุปค่ะ"], tools_that_record([]))
    assert text.count("✅ `web_search`") == 1 and text.count("⏭️ `web_search`") == 1


async def test_what_a_tool_was_asked_never_reaches_the_channel(monkeypatch):
    # The arguments are what members asked: a phone number, a name, a reminder, a search.
    secrets = ["0812345678", "ความลับของ Ploy", "ซื้อของขวัญวันเกิดเนยใส"]

    @tool
    def memory_search(query: str, ctx: Ctx) -> str:
        """Search the notes."""
        return "No note found."

    for secret in secrets:
        for name, tools in (("lookup", tools_that_record([])), ("memory_search", [memory_search])):
            text = await embed_of_a_turn(monkeypatch, [tool_call(name, query=secret), "ค่ะ"], tools)
            assert secret not in text and "[phone]" not in text
            assert f"`{name}`" in text  # which tool ran is shown, what it was asked is not


async def test_nothing_in_the_embed_but_numbers_names_and_marks(monkeypatch):
    text = await embed_of_a_turn(monkeypatch, [tool_call("lookup", query="x"), "คำตอบลับ"], tools_that_record([]))
    assert "x'" not in text and "query" not in text and "คำตอบลับ" not in text and "results for" not in text
