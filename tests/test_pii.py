"""Hiding personal data in what other people wrote before it reaches the model provider."""

import dataclasses
from collections import Counter

import pytest
from langchain_core.tools import tool

from tests.fakes import ScriptedChat, call
from utils.ai import agent
from utils.ai.agent import run_agent
from utils.ai.context import Ctx, YuukaContext
from utils.ai import pii
from utils.ai.pii import hide, luhn_valid, redact, thai_id_valid


def make_thai_id(first12: str) -> str:
    total = sum(int(d) * (13 - i) for i, d in enumerate(first12))
    return first12 + str((11 - total % 11) % 10)


VALID_ID = make_thai_id("110170020345")


def test_checksums():
    assert thai_id_valid(VALID_ID)
    assert not thai_id_valid(VALID_ID[:-1] + str((int(VALID_ID[-1]) + 1) % 10))
    assert not thai_id_valid("12345")
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


@pytest.mark.parametrize(
    "text, kind",
    [
        ("โทรมาที่ 0812345678 นะ", "[phone]"),
        ("เบอร์0812345678ครับ", "[phone]"),
        ("โทร 081-234-5678", "[phone]"),
        ("โทร 081 234 5678", "[phone]"),
        ("ออฟฟิศ 02-123-4567", "[phone]"),
        ("เบอร์โทรติดต่อ 07-777-7777", "[phone]"),
        ("call +66 81 234 5678", "[phone]"),
        ("call +66812345678", "[phone]"),
        ("mail me at sensei.yuuka+test@example.co.th", "[email]"),
        (f"บัตร ปชช. {VALID_ID}", "[thai-id]"),
        (f"บัตร {VALID_ID[0]}-{VALID_ID[1:5]}-{VALID_ID[5:10]}-{VALID_ID[10:12]}-{VALID_ID[12]}", "[thai-id]"),
        ("card 4111 1111 1111 1111", "[card]"),
        ("card 4111-1111-1111-1111", "[card]"),
        ("amex 3782 822463 10005", "[card]"),
    ],
)
def test_personal_data_is_hidden(text, kind):
    out = redact(text)
    assert kind in out
    assert not any(ch.isdigit() for ch in out.replace("66", "")) or kind == "[email]"


def test_the_words_around_it_stay():
    assert redact("เซนเซย์ โทร 0812345678 ได้เลย") == "เซนเซย์ โทร [phone] ได้เลย"


@pytest.mark.parametrize(
    "text",
    [
        "[2026-10-11 20:15 UTC+7] Nick: ไปกินข้าวกัน",
        "วันที่ 2026-10-11 เวลา 20:15:30",
        "เจอกัน 11/10/2026",
        "ราคา 1,250,000 บาท",
        "เปิดเพลงที่ 3",
        "version 3.2.3",
        "0.5 ส่วน",
    ],
)
def test_ordinary_numbers_stay(text):
    assert redact(text) == text


def test_an_id_that_fails_its_checksum_stays():
    wrong = VALID_ID[:-1] + str((int(VALID_ID[-1]) + 1) % 10)
    assert redact(f"เลข {wrong}") == f"เลข {wrong}"


def test_a_number_that_fails_luhn_stays():
    assert redact("order 4111111111111112") == "order 4111111111111112"


def test_discord_links_and_mentions_are_never_touched():
    # A Discord ID is 17-19 digits; some of them would pass Luhn.
    ids = ["123456789012345678", "4111111111111111", "1101700203451"]
    for number in ids:
        link = f"<https://discord.com/channels/{number}/{number}/{number}>"
        text = f"Nick: ดูนี่ {link} <#{number}> <@{number}> https://example.com/{number}"
        assert redact(text) == text


def test_counts_say_how_many_never_what():
    counts = Counter()
    redact(f"0812345678 และ 0898765432 กับ a@b.com {VALID_ID}", counts)
    assert counts == {"phone": 2, "email": 1, "id": 1}


# ── Applied to what the tools bring back ──────────────────────────────────

CTX = YuukaContext(bot=None, guild=None, requester=None, channel=None)
HISTORY = [{"role": "system", "content": "You are Yuuka."}, {"role": "user", "content": "สรุปให้หน่อย"}]


def fake_tools():
    @tool
    def read_messages(channel: str, ctx: Ctx) -> str:
        """Read a channel."""
        return "Ploy: โทรหาเราได้ที่ 0812345678 นะ"

    @tool
    def lookup(query: str, ctx: Ctx) -> str:
        """Not a tool that reads other people's text."""
        return "tel 0812345678"

    return [read_messages, lookup]


async def sent_to_model(tool_name, monkeypatch=None, **cfg):
    model = ScriptedChat(replies=[call(tool_name, **({"channel": "general"} if tool_name == "read_messages" else {"query": "x"})), "สรุปแล้วค่ะ"])
    [e async for e in run_agent(list(HISTORY), CTX, tools=fake_tools(), model=model)]
    return str([m.content for m in model.seen[1]])


async def test_a_channel_read_is_redacted_before_the_model_sees_it():
    seen = await sent_to_model("read_messages")
    assert "[phone]" in seen and "0812345678" not in seen


async def test_a_tool_that_does_not_read_other_peoples_text_is_left_alone():
    assert "0812345678" in await sent_to_model("lookup")


async def test_the_flag_turns_it_off(monkeypatch):
    monkeypatch.setattr(agent, "config", dataclasses.replace(agent.config, ai_redact_pii=False))
    assert "0812345678" in await sent_to_model("read_messages")


# ── Text that goes into her history without passing through a tool ────────

def test_hide_redacts_and_the_flag_turns_it_off(monkeypatch):
    assert hide("เบอร์โทรติดต่อ 07-777-7777", "channel history") == "เบอร์โทรติดต่อ [phone]"
    monkeypatch.setattr(pii, "config", dataclasses.replace(pii.config, ai_redact_pii=False))
    assert hide("เบอร์โทรติดต่อ 07-777-7777", "channel history") == "เบอร์โทรติดต่อ 07-777-7777"
