"""
utils/attendance.py
The /attendance and /absent reports, built without a slash-command context so the
commands (`cogs/voice/attendance.py`) and the agent's tools
(`utils/ai/tools/attendance.py`) produce exactly the same embed and CSV.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

import discord
import pytz

from utils.embeds import build_embed

_COLUMNS = ["Number", "Display Name", "Username", "User ID", "Top Role", "Joined Server At"]
_LIST_FIELD_MAX = 1024


@dataclass
class Report:
    embed: discord.Embed
    file: discord.File
    names: list[str]  # display names, in the order of the list


def _list_text(members: list[discord.Member]) -> str:
    text = "".join(f"> {m.display_name}\n" for m in members) or "-"
    return text[: _LIST_FIELD_MAX - 4] + "..." if len(text) > _LIST_FIELD_MAX else text


def _csv(title: str, extra_column: str, rows: list[list], executed_by: str) -> io.BytesIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([title])
    writer.writerow([*_COLUMNS, extra_column])
    for row in rows:
        writer.writerow(row)
    writer.writerow([])
    writer.writerow([f"Time: {datetime.now(pytz.timezone('Asia/Bangkok')).strftime('%H:%M:%S')}"])
    writer.writerow([f"Executed by {executed_by}"])
    # utf-8-sig so Excel opens the Thai text correctly.
    return io.BytesIO(buffer.getvalue().encode("utf-8-sig"))


def _row(index: int, m: discord.Member, last: str) -> list:
    joined_at = m.joined_at.strftime("%Y-%m-%d %H:%M:%S") if m.joined_at else "-"
    top_role = m.top_role.name if m.top_role else "-"
    return [index, m.display_name, str(m.name), str(m.id), top_role, joined_at, last]


def attendance_report(vc: discord.VoiceChannel, executed_by: str) -> Report:
    """Who is in `vc` right now (bots left out)."""
    members = [m for m in vc.members if not m.bot]
    rows = [
        _row(i, m, m.activity.name if m.activity else "-")
        for i, m in enumerate(members, 1)
    ]
    data = _csv(f"บันทึกการเข้าประชุม {vc.name}", "Activity", rows, executed_by)

    embed = build_embed(title="📝 บันทึกการเข้าประชุม", color=0x0A50C8)
    embed.timestamp = datetime.now(pytz.utc)
    embed.add_field(name="🔊 ช่องเสียง", value=f"`{vc.name}`", inline=False)
    embed.add_field(name="👥 จำนวนผู้เข้าร่วม", value=f"`{len(members)} คน`", inline=False)
    embed.add_field(name="👤 รายชื่อ", value=_list_text(members), inline=False)
    return Report(embed, discord.File(fp=data, filename=f"attendance_{vc.id}.csv"),
                  [m.display_name for m in members])


def absent_report(
    guild: discord.Guild,
    vc: discord.VoiceChannel,
    executed_by: str,
    role: discord.Role | None = None,
) -> Report:
    """Members (of `role`, if given) who are not in `vc`; bots left out."""
    absent = [
        m for m in guild.members
        if not m.bot
        and (role is None or role in m.roles)
        and (not m.voice or m.voice.channel != vc)
    ]
    role_name = role.name if role else "-"
    rows = [_row(i, m, role_name) for i, m in enumerate(absent, 1)]
    data = _csv(f"บันทึกการขาดประชุม {vc.name}", "Queried Role", rows, executed_by)

    embed = build_embed(title="📝 บันทึกการขาดประชุม", color=0xFF3C5B)
    embed.timestamp = datetime.now(pytz.utc)
    if role:
        embed.add_field(name="🎩 บทบาท", value=f"`{role.name}`", inline=False)
    embed.add_field(name="🔊 ช่องเสียง", value=f"`{vc.name}`", inline=False)
    embed.add_field(name="👥 จำนวนผู้ขาด", value=f"`{len(absent)} คน`", inline=False)
    embed.add_field(name="👤 รายชื่อ", value=_list_text(absent), inline=False)
    return Report(embed, discord.File(fp=data, filename=f"absent_{vc.id}.csv"),
                  [m.display_name for m in absent])
