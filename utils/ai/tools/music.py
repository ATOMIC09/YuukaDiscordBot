"""
utils/ai/tools/music.py
Music control as tools. They run the same code as the /music commands through
`utils.ai_actions.run_action`, which also posts the embed that documents it.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from rapidfuzz import fuzz

from utils import ai_actions
from utils.ai.context import Ctx, YuukaContext
from utils.errors import UserError

_MAX_LISTED = 25

# Below this a spoken or typed name is not taken to be a queued title.
_TITLE_MATCH_MIN = 75


async def _run(
    ctx: YuukaContext, name: str, arg: str = "", shown: str = ""
) -> tuple[str, ai_actions.ActionResult | None]:
    """`shown` is what the "running" notice prints instead of `arg`, when `arg` is a bare number."""
    if ctx.before_action is not None:
        await ctx.before_action("")

    result = await ai_actions.run_action(
        ctx.bot,
        name=name,
        arg=arg,
        shown=shown,
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
    Plain skip: ข้าม, ข้ามเพลง, เปลี่ยนเพลง, เพลงต่อไป, เอาเพลงอื่น, next, skip.
    """
    if position and song:
        raise UserError("ระบุมาสองอย่างค่ะ", "ให้ระบุแค่ลำดับหรือชื่อเพลงอย่างใดอย่างหนึ่งนะคะ")
    upcoming = _upcoming(ctx)
    if song:
        position = _position_of(upcoming, song)
    # The notice names the song it is about to jump to, not just a number.
    shown = f"#{position} {upcoming[position - 1].title}" if 0 < position <= len(upcoming) else ""
    return await _run(ctx, "music_skip", str(position) if position > 0 else "", shown)


@tool(return_direct=True, response_format="content_and_artifact")
async def music_stop(ctx: Ctx):
    """Stop playback AND clear the whole queue. This cannot be undone, so use it only when the user clearly wants everything gone.

    Use for: ล้างคิว, ล้างเพลงทั้งหมด, เลิกเปิด, เลิกเล่น, เลิกฟัง, ไม่ฟังแล้ว, ปิดเพลง, ปิดเพลงเลย,
    เอาออกให้หมด, stop everything, clear the queue, stop and clear, turn the music off.
    NOT for a bare "หยุด", "หยุดก่อน", "หยุดแป๊บ", "หยุดเพลง" or "stop": those are music_pause.
    """
    return await _run(ctx, "music_stop")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_pause(ctx: Ctx):
    """Pause the song that is playing; music_resume continues it from the same spot. The queue is kept, so this is the safe choice when unsure.

    Use for a bare or soft stop: หยุด, หยุดก่อน, หยุดแป๊บ, หยุดแปป, หยุดเพลง, หยุดเล่น, พักก่อน,
    พักเพลง, รอแป๊บ, เงียบก่อน, ขอเงียบ, pause, stop, hold on, wait.
    Only use music_stop when the user also asks to clear or end everything (ล้างคิว, เลิกเปิด, ปิดเพลง).
    """
    return await _run(ctx, "music_pause")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_resume(ctx: Ctx):
    """Continue a song that was paused.

    Use for: เล่นต่อ, เปิดต่อ, เปิดเพลงต่อ, ต่อเลย, เอาต่อ, ไปต่อ, เล่นเลย, เล่นอีก, กลับมาเล่น,
    resume, continue, unpause, keep playing. Needs a paused song: to start a new one use music_play.
    """
    return await _run(ctx, "music_resume")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_seek(timestamp: str, ctx: Ctx):
    """Jump to a time in the song that is playing.

    `timestamp` is seconds or minutes:seconds the user said ("90", "1:30", "1:02:03").
    Convert spoken times yourself: "สองนาทีครึ่ง" is "2:30", "นาทีที่ 3" is "3:00".
    To restart the song use "0": ตั้งแต่ต้น, เล่นใหม่, เล่นเพลงนี้ใหม่, เริ่มใหม่, from the start, restart.
    Use for: ไปที่, กรอไปที่, เลื่อนไป, ข้ามไปที่นาที, seek, jump to.
    """
    return await _run(ctx, "music_seek", timestamp)


@tool(return_direct=True, response_format="content_and_artifact")
async def music_previous(ctx: Ctx):
    """Go back to the song that played before the current one.

    Use for: ย้อนกลับ, เพลงก่อนหน้า, เพลงที่แล้ว, เล่นเพลงที่แล้ว, กลับไปเพลงเมื่อกี้, previous, go back.
    To restart the song that is playing now use music_seek with "0" instead.
    """
    return await _run(ctx, "music_previous")


@tool(return_direct=True, response_format="content_and_artifact")
async def music_loop(mode: Literal["off", "track", "queue"], ctx: Ctx):
    """Set looping: "track" repeats the current song, "queue" repeats the whole queue, "off" turns it off.

    "track": วนเพลงนี้, เล่นซ้ำเพลงนี้, ซ้ำเพลงนี้, เปิดซ้ำ, วนซ้ำ, loop this song, repeat this song.
    "queue": วนทั้งคิว, วนทั้งหมด, เล่นซ้ำทั้งคิว, วนลิสต์, loop the queue, repeat all.
    "off": เลิกวน, ไม่ต้องวน, ปิดวนซ้ำ, ปิดลูป, หยุดวน, stop looping, loop off.
    """
    return await _run(ctx, "music_loop", mode)


@tool(return_direct=True, response_format="content_and_artifact")
async def music_volume(level: int, ctx: Ctx):
    """Set the music volume from 0 to 100.

    A number the user said is used as it is ("เสียง 30" is 30). For relative requests start from
    the Volume in the [MUSIC] notice: ดังขึ้น, เร่งเสียง, เพิ่มเสียง, louder is +15 (หน่อย: +10);
    เบาลง, ลดเสียง, เสียงเบาหน่อย, quieter is -15. ดังสุด, max is 100. ปิดเสียง, mute is 0.
    Clamp to 0-100. Changing the volume never pauses or stops the song.
    """
    return await _run(ctx, "music_volume", str(level))


@tool(return_direct=True, response_format="content_and_artifact")
async def music_leave(ctx: Ctx):
    """Leave the voice channel: stops the music, clears the queue and ends the voice chat. Only when the user asks HER to leave the room.

    Use for: ออกไป, ออกจากห้อง, ออกไปได้แล้ว, ไปได้แล้ว, ไปก่อนนะ, กลับไปได้แล้ว, เลิกคุย, บ๊ายบาย,
    leave, go away, get out of the channel, bye. NOT for stopping or pausing the music (music_pause,
    music_stop), and NOT for kicking someone else (voice_kick).
    """
    if ctx.before_action is not None:
        # She cannot speak once she has left, so the goodbye comes first.
        await ctx.before_action("ไว้เจอกันใหม่นะคะ เซนเซย์" if ctx.voice else "")
    return await _run(ctx, "music_leave")


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
    paused = state.voice_client is not None and state.voice_client.is_paused()
    return (
        f"\n\n[MUSIC] {'Paused' if paused else 'Playing right now'}: "
        f"{state.current.title} <{state.current.original_url}>. "
        f"Songs waiting in the queue: {waiting}. "
        f"Volume: {round(state.volume * 100)}%. Loop: {state.loop_mode}."
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
    await ai_actions.log_command(
        ctx.bot, guild=ctx.guild, channel=ctx.channel, member=ctx.requester,
        command=f"/music remove position={position}", ok=True, detail=track.title,
    )
    return f"Removed: {_describe(track)}"


TOOLS = [
    music_play, music_skip, music_stop, music_pause, music_resume, music_seek, music_previous,
    music_loop, music_volume, music_leave,
    music_now_playing, music_queue, music_history, music_remove,
]

# The command embed already tells the user what is happening.
STATUS: dict = {}
