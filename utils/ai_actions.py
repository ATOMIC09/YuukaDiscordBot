"""
utils/ai_actions.py
The bridge between an `[ACTION: ...]` tag from the LLM and a real bot command.

Why this exists
---------------
`utils.llm` can tell you the model asked for `music_play`, but it has no idea
what a guild or a voice channel is. The cogs know that, but each of them would
otherwise grow its own copy of "parse the intent, find the cog, run the thing,
report what happened". This module is the single place that knows:

  * which actions exist at all (`ACTIONS`), and how to describe them to the model
    (`catalog_for` — a model is never told about an action whose cog is not
    loaded, so it cannot ask for something that would only fail),
  * how to actually run one (`run_action`),
  * and what the user sees while it runs.

That last point is not cosmetic. When Yuuka runs a command on her own initiative
there is no slash-command invocation in the channel to point at afterwards, so
the embed *is* the audit trail: it names the command, the argument, the person
whose request triggered it, and how it turned out. It follows the same
post-then-edit shape as the web-search status embed in `utils.llm`, so
AI-initiated work looks consistent wherever it shows up.

Voice sessions
--------------
Running an action never disturbs an active `/ai voice` session. A guild has one
`discord.VoiceClient` and the music player and her TTS both go through it, so
she cannot *speak* while a track is playing — but she can still listen, think,
and answer in the text channel, which is what she does. See
`AIVoiceChatCog._speak`.

The one hard constraint that remains is ordering: `vc.play()` raises on a client
that is already playing, so the caller must let any spoken acknowledgement
finish before an action starts a track.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import discord

from bot.logger import logger
from utils.embeds import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS, build_embed
from utils.errors import UserError, UserWarning

_PLAYER_COG = "PlayerCog"


@dataclass(frozen=True)
class ActionSpec:
    """One action the model may request, and how it is described to the model."""

    tag: str            # what goes inside [ACTION: ...]
    command: str        # the slash command it stands in for, for the embed
    description: str    # shown to the model in the catalog
    requires_cog: str = ""


@dataclass
class ActionResult:
    """What happened, and what the caller still has to do about it."""

    ok: bool
    title: str
    detail: str
    # Spoken when the model gave no acknowledgement of its own (it usually does).
    spoken_fallback: str = ""


ACTIONS: dict[str, ActionSpec] = {
    "music_play": ActionSpec(
        tag="music_play | song name or URL",
        command="/music play",
        description="play or queue a song in the voice channel the user is in",
        requires_cog=_PLAYER_COG,
    ),
    "music_skip": ActionSpec(
        tag="music_skip",
        command="/music skip",
        description="skip the song playing right now",
        requires_cog=_PLAYER_COG,
    ),
    "music_stop": ActionSpec(
        tag="music_stop",
        command="/music stop",
        description="stop playback and clear the whole queue",
        requires_cog=_PLAYER_COG,
    ),
}


def catalog_for(bot: discord.Bot) -> str:
    """Render the actions this bot can currently run, for the system prompt.

    An action whose cog failed to load is left out entirely rather than offered
    and then refused — the model cannot ask for what it was never told about.
    """
    lines = [
        f"[ACTION: {spec.tag}] — {spec.description}"
        for spec in ACTIONS.values()
        if not spec.requires_cog or bot.get_cog(spec.requires_cog) is not None
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────────────────────────────────────


async def _music_play(
    bot: discord.Bot,
    guild: discord.Guild,
    member: discord.Member,
    arg: str,
    text_channel: Any,
) -> ActionResult:
    if not arg:
        return ActionResult(
            False,
            "ไม่รู้ว่าจะเปิดเพลงอะไรค่ะ",
            "หนูไม่แน่ใจว่าเซนเซย์อยากฟังเพลงไหนนะคะ บอกชื่อเพลงอีกทีได้มั้ยคะ (´・ω・)",
            spoken_fallback="หนูไม่แน่ใจว่าจะเปิดเพลงอะไรดีค่ะ บอกชื่อเพลงอีกทีนะคะ",
        )

    voice = getattr(member, "voice", None)
    if not voice or not voice.channel:
        return ActionResult(
            False,
            "เซนเซย์ยังไม่ได้เข้าห้องเสียงค่ะ",
            "เข้าห้องเสียงก่อนนะคะ แล้วหนูจะเปิดเพลงให้เลยค่า (・`ω´・)",
            spoken_fallback="เซนเซย์ยังไม่ได้อยู่ในห้องเสียงเลยค่ะ เข้ามาก่อนนะคะ",
        )

    player = bot.get_cog(_PLAYER_COG)
    result = await player.enqueue_query(
        guild=guild,
        requester=member,
        voice_channel=voice.channel,
        text_channel=text_channel,
        query=arg,
    )

    if not result.ok:
        return ActionResult(
            False,
            result.error_title,
            result.error_detail,
            spoken_fallback="ขอโทษค่ะ หนูหาเพลงนั้นไม่เจอเลย",
        )

    if result.is_playlist:
        detail = f"เพิ่ม Playlist ({result.added} เพลง) ลงคิวแล้วค่ะ"
    else:
        track = result.first_track
        detail = f"เพิ่ม [{track.title}]({track.original_url}) ลงคิวแล้วค่ะ"

    return ActionResult(
        True,
        "เปิดเพลงให้แล้วค่ะ",
        detail,
        spoken_fallback="ได้ค่ะ เดี๋ยวหนูเปิดเพลงให้เลยนะคะ",
    )


async def _music_skip(
    bot: discord.Bot,
    guild: discord.Guild,
    member: discord.Member,
    arg: str,
    text_channel: Any,
) -> ActionResult:
    player = bot.get_cog(_PLAYER_COG)
    next_track = await player.skip_current(guild)
    detail = (
        f"เพลงต่อไปคือ [{next_track.title}]({next_track.original_url}) ค่ะ"
        if next_track
        else "ข้ามให้แล้วค่ะ แต่ไม่มีเพลงในคิวต่อแล้วนะคะ"
    )
    return ActionResult(
        True,
        "ข้ามเพลงให้แล้วค่ะ",
        detail,
        spoken_fallback="ข้ามให้แล้วค่ะ",
    )


async def _music_stop(
    bot: discord.Bot,
    guild: discord.Guild,
    member: discord.Member,
    arg: str,
    text_channel: Any,
) -> ActionResult:
    player = bot.get_cog(_PLAYER_COG)
    await player.stop_playback(guild)
    return ActionResult(
        True,
        "หยุดเพลงแล้วค่ะ",
        "หนูหยุดเพลงและเคลียร์คิวให้หมดแล้วนะคะ (・`ω´・)",
        spoken_fallback="หยุดเพลงให้แล้วค่ะ",
    )


_HANDLERS: dict[str, Callable[..., Awaitable[ActionResult]]] = {
    "music_play": _music_play,
    "music_skip": _music_skip,
    "music_stop": _music_stop,
}


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────


def _target_channel(bot: discord.Bot, guild: discord.Guild, fallback: Any) -> Any:
    """Where a command embed goes: the player's channel, else the caller's."""
    player = bot.get_cog(_PLAYER_COG)
    if player is not None:
        state = player.get_state(guild.id)
        if state.text_channel is not None:
            return state.text_channel
    return fallback


def _running_embed(spec: ActionSpec, arg: str, requester: str) -> discord.Embed:
    body = f"หนูขอเรียกใช้ `{spec.command}` ให้นะคะ"
    if arg:
        body += f"\n> `{arg}`"
    return build_embed(
        "⚙️ กำลังเรียกใช้คำสั่ง",
        body,
        COLOR_INFO,
        footer=f"🤖 หนูสั่งเองตามคำขอของ {requester}",
    )


def _done_embed(spec: ActionSpec, result: ActionResult, requester: str) -> discord.Embed:
    icon = "✅" if result.ok else "❌"
    return build_embed(
        f"{icon} `{spec.command}` — {result.title}",
        result.detail,
        COLOR_SUCCESS if result.ok else COLOR_ERROR,
        footer=f"🤖 หนูสั่งเองตามคำขอของ {requester}",
    )


async def run_action(
    bot: discord.Bot,
    *,
    name: str,
    arg: str,
    guild: discord.Guild,
    member: discord.Member,
    fallback_channel: Any,
) -> ActionResult | None:
    """Execute one model-requested action and post the embed that documents it.

    Returns None for an action name the model made up, which is the caller's cue
    to treat the turn as ordinary conversation. Never raises: a handler blowing
    up becomes a failed `ActionResult` with a red embed, because the caller is
    usually mid-conversation and has a session to keep coherent.
    """
    spec = ACTIONS.get(name)
    if spec is None:
        logger.warning(f"[AI Action] Model requested unknown action '{name}' in guild {guild.id}")
        return None

    if spec.requires_cog and bot.get_cog(spec.requires_cog) is None:
        logger.error(f"[AI Action] '{name}' needs cog '{spec.requires_cog}', which is not loaded")
        return ActionResult(
            False,
            "ใช้คำสั่งนั้นไม่ได้ค่ะ",
            "ระบบเพลงยังไม่พร้อมใช้งานตอนนี้นะคะ (´-ω-`)",
            spoken_fallback="ขอโทษค่ะ ตอนนี้หนูใช้คำสั่งนั้นไม่ได้",
        )

    requester = member.display_name
    channel = _target_channel(bot, guild, fallback_channel)

    logger.info(f"[AI Action] Running '{name}' for {requester} in guild {guild.id}: {arg or '—'}")

    notice = None
    try:
        notice = await channel.send(embed=_running_embed(spec, arg, requester))
    except discord.HTTPException as exc:
        logger.warning(f"[AI Action] Could not post the notice embed: {exc}")

    try:
        result = await _HANDLERS[name](bot, guild, member, arg, channel)
    except (UserError, UserWarning) as exc:
        # The player raises these for ordinary refusals — nothing is playing,
        # the queue position does not exist. They are answers, not faults.
        result = ActionResult(False, exc.title, exc.description, spoken_fallback=exc.title)
    except Exception as exc:
        logger.exception(f"[AI Action] '{name}' failed in guild {guild.id}: {exc}")
        result = ActionResult(
            False,
            "ทำคำสั่งไม่สำเร็จค่ะ",
            "อ๊ะ! มีอะไรผิดพลาดตอนหนูเรียกคำสั่งค่ะ หนูจดไว้ให้ผู้พัฒนาแล้วน้า (´-ω-`)",
            spoken_fallback="ขอโทษค่ะ หนูทำคำสั่งนั้นไม่สำเร็จ",
        )

    embed = _done_embed(spec, result, requester)
    try:
        if notice is not None:
            await notice.edit(embed=embed)
        else:
            await channel.send(embed=embed)
    except discord.HTTPException as exc:
        logger.warning(f"[AI Action] Could not post the result embed: {exc}")

    return result
