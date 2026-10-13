"""Tool calling for a model that has none: calls are parsed out of plain text."""

import dataclasses

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from tests.fakes import ScriptedChat, call
from utils.ai import tool_calling
from utils.ai.tool_calling import FABRICATED, ToolPromptChatModel, _parse_call, _parse_harmony


# ── Reading a call ────────────────────────────────────────────────────────

def test_clean_call():
    assert _parse_call('{"name": "web_search", "arguments": {"query": "x"}}') == {
        "name": "web_search",
        "args": {"query": "x"},
    }


def test_code_fence_and_args_alias():
    assert _parse_call('```json\n{"name": "a", "args": {"n": 1}}\n```') == {"name": "a", "args": {"n": 1}}


def test_arguments_written_as_a_string():
    assert _parse_call('{"name": "a", "arguments": "{\\"n\\": 1}"}') == {"name": "a", "args": {"n": 1}}


@pytest.mark.parametrize("junk", ["}", " </tool_call}", " trailing words"])
def test_junk_after_the_json_is_ignored(junk):
    assert _parse_call('{"name": "a", "arguments": {"n": 1}}' + junk) == {"name": "a", "args": {"n": 1}}


@pytest.mark.parametrize("raw", ["this is not json", "[1, 2]", '{"arguments": {}}'])
def test_unreadable_call_is_none(raw):
    assert _parse_call(raw) is None


def test_harmony_names_the_tool_in_the_recipient():
    raw = '<|channel|>commentary to=functions.web_search <|constrain|>json<|message|>{"query": "x"}'
    assert _parse_harmony(raw) == {"name": "web_search", "args": {"query": "x"}}


def test_harmony_call_nested_in_our_tags_with_an_escaped_slash():
    raw = '<|channel|>commentary to=functions.a<|message|><tool_call>{"name": "a", "arguments": {"n": 1}}<\\/tool_call>'
    assert _parse_harmony(raw) == {"name": "a", "args": {"n": 1}}


# ── The streaming wrapper ─────────────────────────────────────────────────

@tool
def web_search(query: str) -> str:
    """Search the web."""
    return query


async def run(replies, *, piece=5, **fields):
    """The chunks `ToolPromptChatModel` yields for one scripted reply, with a tool on offer."""
    inner = ScriptedChat(replies=list(replies), piece=piece)
    model = ToolPromptChatModel(inner=inner, **fields).bind_tools([web_search])
    return [chunk async for chunk in model.astream([HumanMessage(content="hi")])]


def text_of(chunks):
    return "".join(c.content for c in chunks if isinstance(c.content, str))


def calls_of(chunks):
    return [(c["name"], c["args"]) for chunk in chunks for c in chunk.tool_call_chunks]


async def test_plain_answer_passes_through():
    chunks = await run(["สวัสดีค่ะ เซนเซย์"])
    assert text_of(chunks) == "สวัสดีค่ะ เซนเซย์"
    assert calls_of(chunks) == []


async def test_call_split_across_chunks_is_read_and_never_shown():
    chunks = await run([call("web_search", query="ข่าววันนี้")], piece=3)
    assert calls_of(chunks) == [("web_search", '{"query": "ข่าววันนี้"}')]
    assert text_of(chunks) == ""


async def test_text_before_a_call_is_dropped():
    chunks = await run(["We need to look this up. " + call("web_search", query="x")])
    assert text_of(chunks) == ""
    assert [name for name, _ in calls_of(chunks)] == ["web_search"]


async def test_several_calls_are_read_in_order():
    chunks = await run([call("music_play", query="a") + call("music_skip")])
    assert [name for name, _ in calls_of(chunks)] == ["music_play", "music_skip"]


async def test_reading_stops_at_the_call_limit(monkeypatch):
    monkeypatch.setattr(tool_calling, "config", dataclasses.replace(tool_calling.config, agent_max_tool_calls=2))
    chunks = await run([call("a") + call("b") + call("c") + call("d")])
    assert [name for name, _ in calls_of(chunks)] == ["a", "b"]


async def test_unreadable_call_drops_the_words_before_it():
    # "The song is ready" would claim something that never happened.
    chunks = await run(["เพลงพร้อมแล้วค่ะ <tool_call>this is not json</tool_call>"])
    assert text_of(chunks) == ""
    assert calls_of(chunks) == []


async def test_model_writing_its_own_tool_response_is_flagged():
    chunks = await run(['ได้เลยค่ะ <tool_response name="web_search">made up</tool_response>'])
    assert any(c.additional_kwargs.get(FABRICATED) for c in chunks)
    assert text_of(chunks) == ""
    assert calls_of(chunks) == []


async def test_reasoning_without_a_call_is_dropped():
    chunks = await run(["We need to call tool web_search."])
    assert text_of(chunks) == ""


async def test_empty_stream_gives_an_empty_chunk():
    chunks = await run([""])
    assert chunks and text_of(chunks) == ""


async def test_long_answer_streams_but_voice_holds_it_whole():
    answer = "ก" * 400
    streamed = await run([answer], piece=20)
    held = await run([answer], piece=20, hold_all=True)
    assert text_of(streamed) == text_of(held) == answer
    assert len([c for c in streamed if c.content]) > 1
    assert len([c for c in held if c.content]) == 1


async def test_voice_holds_reasoning_longer_than_the_preamble_before_a_call():
    # A voice turn once read 3400 characters of reasoning aloud before its kick call.
    reasoning = "For voice chat my spoken words come from my replies. " * 20
    chunks = await run([reasoning + call("voice_kick", member="me")], piece=40, hold_all=True)
    assert text_of(chunks) == ""
    assert [name for name, _ in calls_of(chunks)] == ["voice_kick"]
