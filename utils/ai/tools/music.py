"""
utils/ai/tools/music.py
Music control as tools. They run the same code as the /music commands through
`utils.ai_actions.run_action`, which also posts the embed that documents it.
"""

from __future__ import annotations

from langchain_core.tools import tool

from utils import ai_actions
from utils.ai.context import Ctx, YuukaContext

_MAX_LISTED = 25


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
    return result.title, result


@tool(return_direct=True, response_format="content_and_artifact")
async def music_play(query: str, ctx: Ctx):
    """Play or queue a song in the voice channel the requester is in.

    `query` must be a song name or URL the user gave, or one found by
    web_search in this conversation. Never make one up.
    """
    return await _run(ctx, "music_play", query)


@tool(return_direct=True, response_format="content_and_artifact")
async def music_skip(ctx: Ctx):
    """Skip the song playing right now."""
    return await _run(ctx, "music_skip")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_stop(ctx: Ctx):
    """Stop playback and clear the whole queue."""
    return await _run(ctx, "music_stop")


def _player(ctx: YuukaContext):
    return ctx.bot.get_cog("PlayerCog")


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
