"""
utils/ai/tools/music.py
Music control as tools. They run the same code as the /music commands through
`utils.ai_actions.run_action`, which also posts the embed that documents it.
"""

from __future__ import annotations

from langchain_core.tools import tool
from rapidfuzz import fuzz

from utils import ai_actions
from utils.ai.context import Ctx, YuukaContext
from utils.errors import UserError

_MAX_LISTED = 25

# Below this a spoken or typed name is not taken to be a queued title.
_TITLE_MATCH_MIN = 75


async def _run(ctx: YuukaContext, name: str, arg: str = "") -> tuple[str, ai_actions.ActionResult | None]:
    if ctx.before_action is not None:
        await ctx.before_action("")

    result = await ai_actions.run_action(
        ctx.bot,
        name=name,
        arg=arg,
        guild=ctx.guild,
        member=ctx.requester,
        fallback_channel=ctx.channel,
    )
    if result is None:
        return "That command does not exist.", None
    # The title alone ("เปิดเพลงให้แล้วค่ะ") says nothing about which song, and this
    # is also what lands in her history.
    return f"{result.title} — {result.detail}", result


@tool(return_direct=True, response_format="content_and_artifact")
async def music_play(query: str, ctx: Ctx):
    """Play or queue a song in the voice channel the requester is in.

    `query` must be a song name or URL the user gave, or one found by
    web_search in this conversation. Never make one up.
    """
    return await _run(ctx, "music_play", query)


def _upcoming(ctx: YuukaContext) -> list:
    """The queue as users see it: the track prepared for crossfade counts as first."""
    state = ctx.bot.get_cog("PlayerCog").get_state(ctx.guild.id)
    return ([state.crossfade_next] if state.crossfade_next else []) + list(state.queue)


def _position_of(upcoming: list, name: str) -> int:
    """1-based queue position of the track whose title best matches `name`."""
    wanted = name.casefold().strip()
    for index, track in enumerate(upcoming, start=1):
        if wanted in track.title.casefold():
            return index
    scores = [fuzz.partial_ratio(wanted, t.title.casefold()) for t in upcoming]
    if scores and max(scores) >= _TITLE_MATCH_MIN:
        return scores.index(max(scores)) + 1
    raise UserError(
        "ไม่เจอเพลงนั้นในคิว",
        f'ในคิวไม่มีเพลงที่ชื่อคล้าย "{name}" ค่ะ (ถ้าเซนเซย์อยากฟังเพลงนี้ ให้เปิดเพลงใหม่แทน)',
    )


@tool(return_direct=True, response_format="content_and_artifact")
async def music_skip(ctx: Ctx, position: int = 0, song: str = ""):
    """Skip the song playing right now, or jump ahead in the queue.

    With neither argument it skips to the next song. To jump ahead give `position`
    (the number in the queue, 1 is the next song: "skip to song 3" is position 3) or
    `song` (part of the title of a song already in the queue). Never give both.
    When the user says "that song" or "the one you just added", pass its title from the
    earlier [result] or tool result as `song`: a plain skip is only for "skip" on its own.
    """
    if position and song:
        raise UserError("ระบุมาสองอย่างค่ะ", "ให้ระบุแค่ลำดับหรือชื่อเพลงอย่างใดอย่างหนึ่งนะคะ")
    if song:
        position = _position_of(_upcoming(ctx), song)
    return await _run(ctx, "music_skip", str(position) if position > 0 else "")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_stop(ctx: Ctx):
    """Stop playback and clear the whole queue."""
    return await _run(ctx, "music_stop")


def _player(ctx: YuukaContext):
    return ctx.bot.get_cog("PlayerCog")


def now_playing_notice(ctx: YuukaContext) -> str:
    """The current song, for the prompt: "replay this song" then needs no lookup.

    A lookup is a call whose result only arrives in a later reply, and a music
    action ends the turn, so without this "stop, wait, play this again" cannot
    be done in one reply.
    """
    state = _player(ctx).get_state(ctx.guild.id)
    if state.current is None:
        return "\n\n[MUSIC] Nothing is playing right now."
    waiting = len(state.queue) + (1 if state.crossfade_next else 0)
    return (
        f"\n\n[MUSIC] Playing right now: {state.current.title} <{state.current.original_url}>. "
        f"Songs waiting in the queue: {waiting}."
    )


def _describe(track) -> str:
    from cogs.voice.player import format_duration

    return (
        f"{track.title} <{track.original_url}> "
        f"(requested by {track.requester.display_name}, {format_duration(track.duration)})"
    )


@tool
async def music_now_playing(ctx: Ctx) -> str:
    """Say what song is playing right now, who asked for it, loop mode and volume."""
    state = _player(ctx).get_state(ctx.guild.id)
    if state.current is None:
        return "Nothing is playing."
    return (
        f"Now playing: {_describe(state.current)}. "
        f"Loop: {state.loop_mode}. Volume: {round(state.volume * 100)}%."
    )


@tool
async def music_queue(ctx: Ctx) -> str:
    """List the songs waiting in the queue with their positions and who requested them."""
    state = _player(ctx).get_state(ctx.guild.id)
    upcoming = ([state.crossfade_next] if state.crossfade_next else []) + list(state.queue)
    if not upcoming:
        return "The queue is empty."

    lines = [f"{i}. {_describe(t)}" for i, t in enumerate(upcoming[:_MAX_LISTED], start=1)]
    if len(upcoming) > _MAX_LISTED:
        lines.append(f"...and {len(upcoming) - _MAX_LISTED} more")
    return "\n".join(lines)


@tool
async def music_history(ctx: Ctx) -> str:
    """List the last songs that were played, newest first. Use a link from here with music_play to play one again."""
    state = _player(ctx).get_state(ctx.guild.id)
    if not state.history:
        return "No songs have been played yet."
    return "\n".join(f"- {_describe(t)}" for t in reversed(state.history))


@tool
async def music_remove(position: int, ctx: Ctx) -> str:
    """Remove one song from the queue by its position (1 is the next song). Check music_queue first."""
    track = await _player(ctx).remove_from_queue(ctx.guild, position)
    return f"Removed: {_describe(track)}"


TOOLS = [music_play, music_skip, music_stop, music_now_playing, music_queue, music_history, music_remove]

# The command embed already tells the user what is happening.
STATUS: dict = {}
