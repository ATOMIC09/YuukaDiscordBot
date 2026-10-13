"""The agent loop, driven by a scripted model and fake tools."""

import dataclasses

from langchain_core.tools import tool

from tests.fakes import ScriptedChat, call
from utils.ai import agent
from utils.ai.agent import run_agent
from utils.ai.context import Ctx, YuukaContext
from utils.errors import UserError

HISTORY = [
    {"role": "system", "content": "You are Yuuka."},
    {"role": "user", "content": "[2026-10-11 20:15 UTC+7] Nick: ช่วยหน่อย"},
]


def make_ctx(*, voice=False) -> YuukaContext:
    return YuukaContext(bot=None, guild=None, requester=None, channel=None, voice=voice)


def tools_that_record(ran: list):
    @tool
    def web_search(query: str, ctx: Ctx) -> str:
        """Search the web."""
        ran.append(("web_search", query))
        return f"results for {query}"

    @tool
    def lookup(query: str, ctx: Ctx) -> str:
        """Look something up."""
        ran.append(("lookup", query))
        return f"found {query}"

    @tool
    def boom(ctx: Ctx) -> str:
        """Always refuses."""
        ran.append(("boom",))
        raise UserError("ทำไม่ได้", "ไม่มีสิทธิ์")

    @tool
    def after(ctx: Ctx) -> str:
        """Runs after something else."""
        ran.append(("after",))
        return "ok"

    @tool(return_direct=True)
    def finish(ctx: Ctx) -> str:
        """Ends the turn."""
        ran.append(("finish",))
        return "finished"

    @tool(return_direct=True)
    def refuse(ctx: Ctx) -> str:
        """Ends the turn, if it works."""
        ran.append(("refuse",))
        raise UserError("ทำไม่ได้", "ไม่มีสิทธิ์")

    return [web_search, lookup, boom, after, finish, refuse]


async def turn(replies, ran=None, *, voice=False, history=HISTORY):
    """Run one turn. Returns the events and the model, whose `seen` holds each prompt."""
    ran = [] if ran is None else ran
    model = ScriptedChat(replies=list(replies), piece=7)
    events = [e async for e in run_agent(list(history), make_ctx(voice=voice), tools=tools_that_record(ran), model=model)]
    return events, model


def kinds(events):
    return [kind for kind, _ in events]


def reply_text(events):
    return "".join(payload for kind, payload in events if kind == "content")


async def test_plain_answer():
    events, model = await turn(["ได้เลยค่ะ เซนเซย์"])
    assert reply_text(events) == "ได้เลยค่ะ เซนเซย์"
    assert "plan" not in kinds(events) and "error" not in kinds(events)
    assert len(model.seen) == 1


async def test_tool_result_goes_back_to_the_model():
    ran = []
    events, model = await turn([call("lookup", query="x"), "เจอแล้วค่ะ"], ran)
    assert ran == [("lookup", "x")]
    assert reply_text(events) == "เจอแล้วค่ะ"
    assert [p for k, p in events if k == "step"] == [(0, "running"), (0, "ok")]
    # The second request carries the result in the form the prompt describes.
    assert '<tool_response name="lookup">' in model.seen[1][-1].content
    assert "found x" in model.seen[1][-1].content


async def test_text_before_a_call_never_reaches_the_reply():
    events, _ = await turn(["We need to look. " + call("lookup", query="x"), "เจอแล้วค่ะ"])
    assert "We need" not in reply_text(events)


async def test_repeated_read_only_call_runs_once():
    ran = []
    events, model = await turn([call("web_search", query="x") * 3, "สรุปแล้วค่ะ"], ran)
    assert ran == [("web_search", "x")]
    (plan,) = [p for k, p in events if k == "plan"]
    assert len(plan) == 1
    assert "Same call as an earlier one" in str([m.content for m in model.seen[1]])


async def test_repeated_action_call_is_not_deduplicated():
    ran = []
    await turn([call("lookup", query="x") * 2, "ok"], ran)  # `lookup` is not in READ_ONLY
    assert ran == [("lookup", "x"), ("lookup", "x")]


async def test_calls_after_a_failure_are_skipped():
    ran = []
    events, model = await turn([call("boom") + call("after"), "ทำไม่ได้ค่ะ"], ran)
    assert ran == [("boom",)]
    assert [p for k, p in events if k == "step"] == [(0, "running"), (0, "failed"), (1, "skipped")]
    assert "Not run: an earlier call" in str([m.content for m in model.seen[1]])
    assert reply_text(events) == "ทำไม่ได้ค่ะ"


async def test_unknown_tool_is_reported_to_the_model():
    events, model = await turn([call("nope"), "ขอโทษค่ะ"])
    assert "No such tool" in str([m.content for m in model.seen[1]])
    assert (0, "failed") in [p for k, p in events if k == "step"]


async def test_return_direct_tool_ends_the_turn_when_it_works():
    ran = []
    events, model = await turn([call("finish")], ran)
    assert ran == [("finish",)]
    assert len(model.seen) == 1
    assert reply_text(events) == ""
    (done,) = [p for k, p in events if k == "done"]
    assert done[0]["tool_calls"][0]["name"] == "finish"
    assert done[1] == {"role": "tool", "content": "finished", "tool_call_id": done[0]["tool_calls"][0]["id"], "name": "finish"}


async def test_return_direct_tool_that_is_refused_goes_back_to_the_model():
    events, model = await turn([call("refuse"), "เซนเซย์ไม่มีสิทธิ์ค่ะ"])
    assert "done" not in kinds(events)
    assert len(model.seen) == 2
    assert reply_text(events) == "เซนเซย์ไม่มีสิทธิ์ค่ะ"


async def test_last_round_runs_without_tools(monkeypatch):
    monkeypatch.setattr(agent, "config", dataclasses.replace(agent.config, agent_max_rounds=2))
    events, model = await turn([call("lookup", query="x"), "ตอบจากที่มีค่ะ"])
    assert "[TOOLS]" in model.seen[0][0].content
    assert "[TOOLS]" not in model.seen[1][0].content
    assert "No more tools this turn" in model.seen[1][-1].content
    assert reply_text(events) == "ตอบจากที่มีค่ะ"


async def test_a_call_in_the_last_round_is_not_run(monkeypatch):
    monkeypatch.setattr(agent, "config", dataclasses.replace(agent.config, agent_max_rounds=2))
    ran = []
    await turn([call("lookup", query="x"), call("lookup", query="y")], ran)
    assert ran == [("lookup", "x")]


async def test_empty_reply_is_asked_again_once():
    events, model = await turn(["", "ได้ค่ะ"])
    assert reply_text(events) == "ได้ค่ะ"
    assert "no usable tool call" in model.seen[1][-1].content


async def test_two_empty_replies_are_reported():
    events, _ = await turn(["", ""])
    assert kinds(events)[-1] == "error"
    assert reply_text(events) == ""


async def test_model_writing_a_tool_response_is_sent_back_once():
    events, model = await turn(['<tool_response name="lookup">made up</tool_response>', "ตอบจริงค่ะ"])
    assert reply_text(events) == "ตอบจริงค่ะ"
    assert "You wrote a <tool_response> yourself" in model.seen[1][-1].content


async def test_voice_turn_never_shows_long_text_before_a_call():
    # Text mode streams a reply that passes 300 characters; a call can only follow in voice.
    ran = []
    events, _ = await turn(["I will now call the tool. " * 30 + call("lookup", query="x"), "เสร็จแล้วค่ะ"], ran, voice=True)
    assert ran == [("lookup", "x")]
    assert reply_text(events) == "เสร็จแล้วค่ะ"
