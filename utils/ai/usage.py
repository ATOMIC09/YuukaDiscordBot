"""
utils/ai/usage.py
What the model costs and how long it takes: tokens and time per call, totals since the bot started
(for /status), and one embed per AI turn in `USAGE_CHANNEL_ID`.

Sizes and timings only. What a member said or what she answered is never recorded here, and the
totals live in RAM: the container is stateless, so they start again at every restart.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import discord

from bot.config import config
from bot.logger import logger

# Teal: apart from the dark grey of the command log and the blue of /status.
_COLOR = discord.Color(0x1ABC9C)


@dataclass(frozen=True)
class CallUsage:
    """One request to the model."""

    provider: str  # "azure/gpt-5.6-luna"; empty when the model does not say
    prompt: int | None  # None: the provider did not report tokens
    reply: int | None
    reasoning: int
    seconds: float  # time spent waiting on the provider, not on Discord
    first_chunk: float | None  # seconds until its first chunk arrived


@dataclass(frozen=True)
class Step:
    """One tool call of a turn, as the usage channel shows it. Its name and outcome only: what it
    was called with is what a member asked, and stays out of the channel."""

    round: int  # which model request chose it, counting from 1
    name: str
    status: str  # ok | failed | skipped
    seconds: float


@dataclass
class Totals:
    calls: int = 0
    prompt: int = 0
    reply: int = 0
    reasoning: int = 0
    seconds: float = 0.0
    slowest: float = 0.0


_totals: dict[str, Totals] = {}
_turns = 0
_fallbacks = 0
_since = time.time()
_tasks: set[asyncio.Task] = set()


def _label(call: CallUsage) -> str:
    return call.provider or "unknown"


def record_turn(calls: list[CallUsage], fallbacks: int = 0) -> None:
    """Add one turn's calls to the totals."""
    global _turns, _fallbacks
    if not calls:
        return
    _turns += 1
    _fallbacks += fallbacks
    for call in calls:
        total = _totals.setdefault(_label(call), Totals())
        total.calls += 1
        total.prompt += call.prompt or 0
        total.reply += call.reply or 0
        total.reasoning += call.reasoning
        total.seconds += call.seconds
        total.slowest = max(total.slowest, call.seconds)


def reset() -> None:
    """Forget the totals (tests)."""
    global _turns, _fallbacks, _since
    _totals.clear()
    _turns = _fallbacks = 0
    _since = time.time()


def summary() -> str:
    """The /status text, or "" when nothing has been asked since the bot started."""
    if not _turns:
        return ""
    lines = [f"คำตอบ: `{_turns:,}` • สลับไปผู้ให้บริการสำรอง: `{_fallbacks:,}` ครั้ง"]
    for name, total in sorted(_totals.items()):
        average = total.seconds / total.calls
        lines.append(
            f"`{name}`: {total.calls:,} คำขอ, token {total.prompt:,} เข้า / {total.reply:,} ออก"
            f" (คิด {total.reasoning:,}), เฉลี่ย {average:.1f}s, ช้าสุด {total.slowest:.1f}s"
        )
    return "\n".join(lines)


_MARKS = {"ok": "✅", "failed": "❌", "skipped": "⏭️"}
_TIMELINE_MAX = 3800  # an embed description holds 4096


def timeline(calls: list[CallUsage], steps: list[Step] | tuple[Step, ...]) -> str:
    """The turn step by step: each model request, and the tool calls it chose under it."""
    lines: list[str] = []
    for number, call in enumerate(calls, start=1):
        tokens = "" if call.prompt is None else f" • {call.prompt:,} เข้า / {call.reply or 0:,} ออก"
        lines.append(f"**รอบ {number}** • `{_label(call)}` • {call.seconds:.2f}s{tokens}")
        for step in (st for st in steps if st.round == number):
            took = "" if step.status == "skipped" else f" {step.seconds:.2f}s"
            lines.append(f"　{_MARKS.get(step.status, '•')} `{step.name}`{took}")
    text = "\n".join(lines)
    if len(text) > _TIMELINE_MAX:
        text = text[:_TIMELINE_MAX].rsplit("\n", 1)[0] + "\n…"
    return text


def turn_embed(
    calls: list[CallUsage], fallbacks: int, voice: bool, steps: list[Step] | tuple[Step, ...] = ()
) -> discord.Embed:
    prompt = sum(c.prompt or 0 for c in calls)
    reply = sum(c.reply or 0 for c in calls)
    reasoning = sum(c.reasoning for c in calls)
    seconds = sum(c.seconds for c in calls)
    first = next((c.first_chunk for c in calls if c.first_chunk is not None), None)
    providers = ", ".join(dict.fromkeys(_label(c) for c in calls))

    embed = discord.Embed(title="📈 AI usage", description=timeline(calls, steps), color=_COLOR)
    embed.add_field(name="โมเดล", value=f"`{providers}`" + (" (สลับไปสำรอง)" if fallbacks else ""), inline=False)
    embed.add_field(name="ช่องทาง", value="เสียง" if voice else "แชท", inline=True)
    embed.add_field(name="คำขอ", value=f"`{len(calls)}`", inline=True)
    embed.add_field(
        name="Token",
        value=f"`{prompt:,}` เข้า / `{reply:,}` ออก" + (f" (คิด `{reasoning:,}`)" if reasoning else ""),
        inline=True,
    )
    embed.add_field(name="เวลารอโมเดล", value=f"`{seconds:.2f}s`", inline=True)
    if first is not None:
        embed.add_field(name="เริ่มตอบหลัง", value=f"`+{first:.2f}s`", inline=True)
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _post(bot: discord.Bot, embed: discord.Embed) -> None:
    channel = bot.get_channel(config.usage_channel_id)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except Exception as exc:
        # The reply is already out; a missing channel or permission must not touch it.
        logger.warning(f"[Usage] Could not post to the usage channel: {type(exc).__name__}")


def finish_turn(
    bot: discord.Bot | None,
    calls: list[CallUsage],
    fallbacks: int,
    voice: bool,
    steps: list[Step] | tuple[Step, ...] = (),
) -> None:
    """Count the turn and post it, in the background: nothing here may slow or break a reply."""
    record_turn(calls, fallbacks)
    if not calls or bot is None or not config.usage_channel_id:
        return
    try:
        task = asyncio.get_running_loop().create_task(_post(bot, turn_embed(calls, fallbacks, voice, steps)))
    except RuntimeError:
        return
    _tasks.add(task)  # a task nobody holds can be collected before it finishes
    task.add_done_callback(_tasks.discard)
