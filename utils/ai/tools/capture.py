"""
utils/ai/tools/capture.py
/record and /transcribe as tools.

They run the same code as the commands (`begin_recording`, `end_recording`,
`begin_captions`, `end_captions`) and need no confirmation. Starting posts the same
"started" embed as the command, so the room can see it is being recorded or
captioned.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool

from utils import ai_actions
from utils.ai.context import Ctx, YuukaContext
from utils.errors import UserError

_RECORD_COG = "Voice Listener"
_CAPTION_COG = "Realtime STT"

# A background task is only weakly referenced by the loop: keep it until it is done.
_delivering: set[asyncio.Task] = set()


def _require_voice(ctx: YuukaContext, what: str) -> None:
    voice = ctx.requester.voice
    if not voice or not voice.channel:
        raise UserError("ยังไม่ได้เข้าห้องเสียง", f"เซนเซย์ต้องอยู่ในห้องเสียงก่อนนะคะ ถึงจะ{what}ได้")


async def _announce(ctx: YuukaContext, embed, command: str, detail: str = "") -> None:
    """Post the embed that tells the room, and log the command with a link to it."""
    message = await ctx.channel.send(embed=embed)
    await ai_actions.log_command(
        ctx.bot, guild=ctx.guild, channel=ctx.channel, member=ctx.requester,
        command=command, ok=True, detail=detail, jump_url=message.jump_url,
    )


@tool
async def record_start(ctx: Ctx) -> str:
    """Run /record start: join the requester's voice channel and record everyone in it as audio files."""
    cog = ctx.bot.get_cog(_RECORD_COG)
    _require_voice(ctx, "อัดเสียง")
    channel = await cog.begin_recording(ctx.guild, ctx.requester, ctx.channel)
    await _announce(ctx, cog.started_embed(channel), "/record start", channel.name)
    return f"Recording started in {channel.name}."


@tool
async def record_stop(ctx: Ctx) -> str:
    """Run /record stop: stop the recording and post the audio files in the chat."""
    cog = ctx.bot.get_cog(_RECORD_COG)
    channel, audio_data = await cog.end_recording(ctx.guild)
    await _announce(ctx, cog.stopped_embed(), "/record stop")

    # Encoding a long recording takes a while, and she should be free meanwhile.
    task = asyncio.create_task(cog.deliver_recording(ctx.guild.id, channel, audio_data))
    _delivering.add(task)
    task.add_done_callback(_delivering.discard)

    return "Recording stopped. The audio files will be posted in the chat in a moment."


@tool
async def transcribe_start(ctx: Ctx) -> str:
    """Run /transcribe start: join the requester's voice channel and post live captions of everything said there, with no wake word."""
    cog = ctx.bot.get_cog(_CAPTION_COG)
    _require_voice(ctx, "ถอดเสียง")
    channel = await cog.begin_captions(ctx.guild, ctx.requester, ctx.channel)
    await _announce(ctx, cog.started_embed(channel, ctx.channel), "/transcribe start", channel.name)
    return f"Live captions started for {channel.name}."


@tool
async def transcribe_stop(ctx: Ctx) -> str:
    """Run /transcribe stop: stop the live captions."""
    cog = ctx.bot.get_cog(_CAPTION_COG)
    await cog.end_captions(ctx.guild)
    await _announce(ctx, cog.stopped_embed(), "/transcribe stop")
    return "Live captions stopped."


RECORD_TOOLS = [record_start, record_stop]
CAPTION_TOOLS = [transcribe_start, transcribe_stop]
RECORD_COG = _RECORD_COG
CAPTION_COG = _CAPTION_COG

STATUS: dict = {}
