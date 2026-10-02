"""
utils/ai/tools/attendance.py
/attendance and /absent as tools. They build the same report as the commands
(`utils.attendance`), post it with its CSV in the text channel, and log it.

They change nothing and act on nobody, so there is no confirm button. The roll
call reads the voice channel the requester is sitting in, so it shows nothing
they could not already see; /absent only names members of the server and says
nothing about any other voice channel.
"""

from __future__ import annotations

import discord
from langchain_core.tools import tool

from utils import ai_actions
from utils.ai.context import Ctx, YuukaContext
from utils.ai.tools.resolve import resolve_role
from utils.attendance import Report, absent_report, attendance_report
from utils.errors import UserError

# Names handed back to the model. The embed and CSV carry the full list.
_MAX_NAMES = 40


def _voice_channel(ctx: YuukaContext, what: str) -> discord.VoiceChannel:
    voice = ctx.requester.voice
    if not voice or not voice.channel:
        raise UserError(
            "ไม่ได้อยู่ในห้องเสียง",
            f"เซนเซย์ต้องอยู่ในห้องเสียงก่อน ถึงจะ{what}ได้นะคะ ┐( ˘_˘)┌",
        )
    return voice.channel


async def _post(ctx: YuukaContext, report: Report, command: str, detail: str) -> None:
    await ctx.channel.send(embed=report.embed, file=report.file)
    await ai_actions.log_command(
        ctx.bot, guild=ctx.guild, channel=ctx.channel, member=ctx.requester,
        command=command, ok=True, detail=detail,
    )


def _names(report: Report) -> str:
    shown = ", ".join(report.names[:_MAX_NAMES]) or "nobody"
    extra = len(report.names) - _MAX_NAMES
    return shown + (f" ...and {extra} more" if extra > 0 else "")


@tool
async def attendance(ctx: Ctx) -> str:
    """Take attendance (เช็คชื่อ): list who is in the voice channel the requester is in, and post the report with a CSV file in the chat. Same as /attendance."""
    vc = _voice_channel(ctx, "เช็คชื่อ")
    report = attendance_report(vc, ctx.requester.display_name)
    await _post(ctx, report, "/attendance", f"{vc.name}: {len(report.names)}")
    return f"Attendance posted for {vc.name}: {len(report.names)} people: {_names(report)}."


@tool
async def absent(ctx: Ctx, role: str | None = None) -> str:
    """Find who is NOT in the voice channel the requester is in (ผู้ขาดประชุม), optionally only members of one role, and post the report with a CSV file in the chat. Same as /absent. `role` is a role name or mention the user gave."""
    vc = _voice_channel(ctx, "หาคนขาด")
    target = resolve_role(ctx, role) if role else None
    report = absent_report(ctx.guild, vc, ctx.requester.display_name, target)
    shown = f"/absent role={target.name}" if target else "/absent"
    await _post(ctx, report, shown, f"{vc.name}: {len(report.names)}")
    scope = f" among {target.name}" if target else ""
    return f"Absence posted for {vc.name}{scope}: {len(report.names)} people: {_names(report)}."


TOOLS = [attendance, absent]

# The report embed already tells the user what happened.
STATUS: dict = {}
