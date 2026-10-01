"""
utils/ai/tools/actions.py
Actions that affect other people. The tool only proposes: it posts a
confirmation and the requester decides (see `utils.ai.confirm`).

Both tools end the turn (`return_direct`) with no ActionResult, so voice does
not speak a second line on top of the one before the call.
"""

from __future__ import annotations

import discord
from langchain_core.tools import tool

from utils.ai.confirm import ConfirmActionView
from utils.ai.context import Ctx, YuukaContext
from utils.ai.tools.resolve import resolve_member
from utils.embeds import info_embed
from utils.errors import UserError, UserWarning

WAITING = "รอเซนเซย์ยืนยันอยู่นะคะ"


def can_move_members(ctx: YuukaContext) -> bool:
    """Mirrors `@discord.default_permissions(move_members=True)` on /kick."""
    return bool(ctx.requester and ctx.requester.guild_permissions.move_members)


def _require_move_members(ctx: YuukaContext) -> None:
    if not can_move_members(ctx):
        raise UserWarning("ทำให้ไม่ได้ค่ะ", "เซนเซย์ไม่มีสิทธิ์ย้ายสมาชิกในห้องเสียงนะคะ")


async def _propose(ctx: YuukaContext, title: str, body: str, action, check) -> str:
    if ctx.before_action is not None:
        await ctx.before_action("กดยืนยันในแชทนะคะ" if ctx.voice else "")

    view = ConfirmActionView(
        bot=ctx.bot, guild=ctx.guild, requester=ctx.requester, action=action, check=check
    )
    view.message = await ctx.channel.send(embed=info_embed(title, body), view=view)
    return WAITING


@tool(return_direct=True)
async def voice_kick(member: str, ctx: Ctx) -> str:
    """Disconnect a member from their voice channel, after the requester confirms with a button."""
    _require_move_members(ctx)
    target = resolve_member(ctx, member)

    if target.id == ctx.bot.user.id:
        raise UserError("จะเตะหนูหรอคะ", "ใจร้ายที่สุดเลย! หนูไม่ยอมหรอกนะ (╯°□°)╯︵ ┻━┻")
    if not target.voice or not target.voice.channel:
        raise UserError("ไม่ได้อยู่ในห้องเสียง", f"ดูเหมือนว่า {target.display_name} จะไม่ได้อยู่ในห้องเสียงนะคะ (●'◡'●)")

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
    )


@tool(return_direct=True)
async def voice_disconnect_timer(seconds: int, ctx: Ctx) -> str:
    """Start a countdown that disconnects everyone in the requester's voice channel when it ends.

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
    )


TOOLS = [voice_kick, voice_disconnect_timer]
STATUS: dict = {}
