"""
utils/ai/tools/actions.py
Actions that affect other people. The tool only proposes: it posts a
confirmation and the requester decides (see `utils.ai.confirm`). The one
exception is a requester who asks to be kicked themselves: nobody else is
touched, so it runs at once. "Kick everyone" is /kick for the whole voice
channel, one confirmation for all; countdis is a different command.

Both tools end the turn (`return_direct`) with no ActionResult: in voice, the
line `_propose` speaks is the only acknowledgement. The requester then answers
by button or, in a voice session, out loud (see `AIVoiceChatCog.expect_answer`).
"""

from __future__ import annotations

import re

import discord
from langchain_core.tools import tool

from bot.logger import logger
from utils import ai_actions
from utils.ai.confirm import ConfirmActionView
from utils.ai.context import Ctx, YuukaContext
from utils.ai.tools.resolve import resolve_member, resolve_member_in
from utils.embeds import info_embed, success_embed
from utils.errors import UserError, UserWarning

WAITING = "รอเซนเซย์ยืนยันอยู่นะคะ"


def can_move_members(ctx: YuukaContext) -> bool:
    """Mirrors `@discord.default_permissions(move_members=True)` on /kick."""
    return bool(ctx.requester and ctx.requester.guild_permissions.move_members)


def _require_move_members(ctx: YuukaContext) -> None:
    if not can_move_members(ctx):
        raise UserWarning("ทำให้ไม่ได้ค่ะ", "เซนเซย์ไม่มีสิทธิ์ย้ายสมาชิกในห้องเสียงนะคะ")


async def _propose(ctx: YuukaContext, title: str, body: str, action, check, command: str) -> str:
    if ctx.before_action is not None:
        await ctx.before_action("พูดว่ายืนยัน หรือกดปุ่มในแชทก็ได้นะคะ" if ctx.voice else "")

    view = ConfirmActionView(
        bot=ctx.bot, guild=ctx.guild, requester=ctx.requester, action=action, check=check,
        command=command,
    )
    view.message = await ctx.channel.send(embed=info_embed(title, body), view=view)
    if ctx.voice:
        voice_cog = ctx.bot.get_cog("AI Voice Chat")
        if voice_cog is not None:
            voice_cog.expect_answer(ctx.guild.id, view)
    return WAITING


async def _run_now(ctx: YuukaContext, kick, command: str) -> str:
    """Run a kick that touches nobody but the requester (and her), so it needs neither the
    permission nor the confirmation: say goodbye, kick, show and log it."""
    if ctx.before_action is not None:
        # Spoken before she acts: once they are gone they cannot hear her.
        await ctx.before_action("บ๊ายบายค่ะ เซนเซย์" if ctx.voice else "")
    line = await kick()
    message = None
    try:
        message = await ctx.channel.send(embed=success_embed("🦵 เรียบร้อยค่ะ", line))
    except discord.HTTPException:
        pass
    await ai_actions.log_command(
        ctx.bot,
        guild=ctx.guild,
        channel=ctx.channel,
        member=ctx.requester,
        command=command,
        ok=True,
        detail=line,
        jump_url=message.jump_url if message is not None else None,
    )
    return line


async def _kick_self(ctx: YuukaContext, target: discord.Member) -> str:
    """The requester asked to be disconnected themselves. Leaving is something anyone may do."""
    channel = target.voice.channel

    async def kick() -> str:
        try:
            await target.move_to(None)
        except discord.Forbidden:
            raise UserWarning("ไม่มีสิทธิ์", "หนูไม่มีสิทธิ์ตัดการเชื่อมต่อในห้องนี้นะคะ (；￣Д￣)")
        return f"เตะ {target.display_name} ออกจากช่อง {channel.name} ตามที่ขอแล้วค่ะ"

    return await _run_now(ctx, kick, f"/kick member={target.display_name}")


# What the model writes for "kick everyone" (เตะทุกคน).
_EVERYONE = frozenset({"everyone", "everybody", "all", "here", "ทุกคน", "ทั้งหมด", "ทั้งห้อง"})
# "everyone except Bob" written into `member` itself, instead of using `keep`.
_EVERYONE_BUT = re.compile(
    r"^@?(?:" + "|".join(sorted(_EVERYONE, key=len, reverse=True)) + r")\s*(?:except|but|ยกเว้น|นอกจาก|เว้น)\s*(.+)$",
    re.I | re.S,
)
# Words in `keep` that mean her. Her name in Latin letters is found in the room like anyone's (her
# display name), so a member called "Yuka" is never mistaken for her.
_HERSELF = frozenset({"you", "yourself", "bot", "ยูกะ", "ยุกะ"})
_NAME_SPLIT = re.compile(r"\s*(?:[,;、\n]|\band\b|และ|กับ)\s*", re.I)


def _kept(ctx: YuukaContext, channel: discord.VoiceChannel, keep: str) -> list[discord.Member]:
    """Who stays when "everyone" is kicked. A name that matches nobody refuses the whole kick:
    better to ask again than to kick the one person they meant to spare."""
    kept: dict[int, discord.Member] = {}
    for name in filter(None, (n.strip() for n in _NAME_SPLIT.split(keep))):
        if name.lstrip("@").casefold() in _HERSELF:
            me = ctx.guild.me
            kept[me.id] = me
            continue
        member = resolve_member_in(ctx, name, channel.members)
        kept[member.id] = member
    return list(kept.values())


def _kick_targets(channel: discord.VoiceChannel, bot_id: int, requester_id: int, kept: set[int]) -> list[discord.Member]:
    """Everyone in `channel` but those kept, her included: the others, then the requester, then her
    last, so her voice session lasts until everyone else is out."""
    members = [m for m in channel.members if m.id not in kept]
    return sorted(members, key=lambda m: (m.id == bot_id, m.id == requester_id))


def _disconnect_all(ctx: YuukaContext, channel: discord.VoiceChannel, kept: list[discord.Member]):
    """The kick for "everyone": whoever is in the room when it runs (at confirm time, not when she
    asked) and not kept, her included, as countdis does."""
    kept_ids = {m.id for m in kept}
    spared = f" ยกเว้น {', '.join(m.display_name for m in kept)}" if kept else ""

    async def kick() -> str:
        gone, refused, herself = 0, 0, False
        for target in _kick_targets(channel, ctx.bot.user.id, ctx.requester.id, kept_ids):
            try:
                await target.move_to(None)
            except discord.Forbidden:
                refused += 1
                continue
            except discord.HTTPException as exc:
                logger.warning(f"[AI Kick] Could not disconnect a member: {exc}")
                refused += 1
                continue
            if target.id == ctx.bot.user.id:
                herself = True
            else:
                gone += 1
        if not (gone or refused or herself):
            raise UserWarning("ไม่มีใครให้เตะแล้วค่ะ", f"ในช่อง {channel.name} ไม่เหลือใครให้เตะแล้วนะคะ")
        line = f"เตะทุกคน {gone} คนออกจากช่อง {channel.name}{spared}{' รวมถึงหนูด้วย' if herself else ''} เรียบร้อยแล้วค่ะ"
        if refused:
            line += f" (เตะไม่ได้ {refused} คน สิทธิ์ของเขาอาจจะสูงกว่าหนู)"
        return line

    return kick


async def _kick_everyone(ctx: YuukaContext, keep: str) -> str:
    """/kick for everyone in the requester's voice channel but those in `keep`, her included: one
    confirmation, then all at once. Not countdis: no countdown and no "except me" button."""
    voice = ctx.requester.voice
    if not voice or not voice.channel:
        raise UserError("ยังไม่ได้เข้าห้องเสียง", "เซนเซย์ต้องอยู่ในห้องเสียงก่อนนะคะ หนูถึงจะรู้ว่าต้องเตะใครบ้าง")
    channel = voice.channel
    kept = _kept(ctx, channel, keep)
    kept_ids = {m.id for m in kept}
    targets = _kick_targets(channel, ctx.bot.user.id, ctx.requester.id, kept_ids)
    if not targets:
        raise UserWarning("ไม่มีใครให้เตะค่ะ", "ทุกคนในห้องอยู่ในรายชื่อที่ให้เว้นไว้หมดเลยนะคะ")
    kick = _disconnect_all(ctx, channel, kept)
    command = "/kick member=everyone" + (f" except={','.join(m.display_name for m in kept)}" if kept else "")
    if all(m.id in (ctx.requester.id, ctx.bot.user.id) for m in targets):
        # Only them and/or her go: nobody else is touched.
        return await _run_now(ctx, kick, command)
    _require_move_members(ctx)

    names = ", ".join(m.display_name for m in targets[:10]) + (" …" if len(targets) > 10 else "")
    spared = f" ยกเว้น {', '.join(m.display_name for m in kept)}" if kept else ""
    return await _propose(
        ctx,
        "🦵 ยืนยันการเตะทุกคนออกจากห้องเสียง",
        f"เซนเซย์ต้องการให้หนูเตะทุกคนในช่อง `{channel.name}`{spared} ({len(targets)} คน: {names}) ออกตอนนี้เลยใช่มั้ยคะ?",
        kick,
        lambda: _require_move_members(ctx),
        command,
    )


@tool(return_direct=True)
async def voice_kick(member: str, ctx: Ctx, keep: str | list[str] = "") -> str:
    """Run the /kick command: disconnect a member from their voice channel, after the requester confirms with a button.

    `member`: their name; "me" for the requester themselves ("kick me", "เตะผมออก", "เตะตัวเอง"), which needs no permission and no confirmation; "everyone" for everyone in the requester's voice channel at once, you included ("kick everyone", "เตะทุกคน"). Kicking everyone is this tool, not countdis: countdis is only for a countdown.
    `keep`: only with "everyone", who stays, comma-separated: names, "me" for the requester, "you" for yourself ("kick everyone except Bob and me", "เตะทุกคนยกเว้นบ็อบกับผม" → member="everyone", keep="Bob, me").
    """
    keep_text = ", ".join(keep) if isinstance(keep, list) else keep
    wanted = member.strip()
    if (but := _EVERYONE_BUT.match(wanted)) is not None:
        wanted, keep_text = "everyone", ", ".join(filter(None, (keep_text, but.group(1))))
    if wanted.lstrip("@").casefold() in _EVERYONE:
        return await _kick_everyone(ctx, keep_text)
    target = resolve_member(ctx, member)

    if target.id == ctx.bot.user.id:
        raise UserError("จะเตะหนูหรอคะ", "ใจร้ายที่สุดเลย! หนูไม่ยอมหรอกนะ (╯°□°)╯︵ ┻━┻")
    if not target.voice or not target.voice.channel:
        raise UserError("ไม่ได้อยู่ในห้องเสียง", f"ดูเหมือนว่า {target.display_name} จะไม่ได้อยู่ในห้องเสียงนะคะ (●'◡'●)")
    if target.id == ctx.requester.id:
        return await _kick_self(ctx, target)
    _require_move_members(ctx)

    async def kick() -> str:
        if not target.voice or not target.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", f"{target.display_name} ออกจากห้องเสียงไปแล้วค่ะ")
        channel = target.voice.channel
        try:
            await target.move_to(None)
        except discord.Forbidden:
            raise UserWarning("ไม่มีสิทธิ์", "หนูไม่มีสิทธิ์เตะคนนี้นะคะ สิทธิ์ของเขาอาจจะสูงกว่าหนู (；￣Д￣)")
        return f"เตะ {target.display_name} ออกจากช่อง {channel.name} เรียบร้อยแล้วค่ะ"

    return await _propose(
        ctx,
        "🦵 ยืนยันการเตะออกจากห้องเสียง",
        f"เซนเซย์ต้องการให้หนูเตะ {target.mention} ออกจากช่อง `{target.voice.channel.name}` ใช่มั้ยคะ?",
        kick,
        lambda: _require_move_members(ctx),
        f"/kick member={target.display_name}",
    )


@tool(return_direct=True)
async def voice_disconnect_timer(seconds: int, ctx: Ctx) -> str:
    """Run the /countdis command: a countdown that disconnects everyone in the requester's voice channel when it ends.

    Use it whenever the user mentions "countdis", "countdown", "นับถอยหลัง", "เค้าดิส" or "เค้าท์ดิส"
    (all spellings of the same command), or asks to disconnect everyone from voice after a delay.
    "Kick everyone" with no countdown is voice_kick with member="everyone", not this.
    `seconds` is the length of the countdown in seconds (10 minutes = 600).
    The requester confirms with a button first.
    """
    from cogs.voice.countdis import format_countdown

    _require_move_members(ctx)
    cog = ctx.bot.get_cog("CountdisCog")
    voice = ctx.requester.voice
    if cog is None or not voice or not voice.channel:
        raise UserError("ยังไม่ได้เข้าห้องเสียง", "เซนเซย์ต้องอยู่ในห้องเสียงก่อนนะคะ ถึงจะตั้งเวลาตัดการเชื่อมต่อได้")
    if seconds <= 0:
        raise UserWarning("เวลาไม่ถูกต้อง", "เวลาต้องมากกว่า 0 วินาทีค่ะ")

    channel = voice.channel
    if channel.id in cog.active_countdowns:
        raise UserWarning("กำลังทำงานอยู่", "หนูกำลังนับถอยหลังของห้องนี้อยู่แล้วค่ะ")

    async def start() -> str:
        await cog.start_countdown(
            channel=channel, seconds=seconds, author=ctx.requester, reply_channel=ctx.channel
        )
        return f"เริ่มนับถอยหลัง {format_countdown(seconds)} ของช่อง {channel.name} แล้วค่ะ"

    return await _propose(
        ctx,
        "⏰ ยืนยันการตั้งเวลาตัดการเชื่อมต่อ",
        f"เซนเซย์ต้องการให้หนูตัดทุกคนออกจากช่อง `{channel.name}` ในอีก **{format_countdown(seconds)}** ใช่มั้ยคะ?",
        start,
        lambda: _require_move_members(ctx),
        f"/countdis channel={channel.name} seconds={seconds}",
    )


TOOLS = [voice_kick, voice_disconnect_timer]
STATUS: dict = {}
