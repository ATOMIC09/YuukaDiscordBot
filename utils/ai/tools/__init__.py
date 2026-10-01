"""
utils/ai/tools/__init__.py
The tools Yuuka may use, picked per turn.
"""

from __future__ import annotations

from typing import Callable

from langchain_core.tools import BaseTool

from utils.ai.context import YuukaContext
from utils.ai.tools import actions, discord_read, music, reminders, search, server

_STATUS: dict[str, Callable[[dict], str]] = {
    **search.STATUS,
    **discord_read.STATUS,
    **server.STATUS,
    **music.STATUS,
    **actions.STATUS,
    **reminders.STATUS,
}


def tools_for(ctx: YuukaContext) -> list[BaseTool]:
    """Only the tools that can work this turn, which also keeps the prompt short."""
    tools: list[BaseTool] = [*search.TOOLS]

    if ctx.guild:
        tools += server.TOOLS

    if ctx.guild and ctx.requester:
        tools += discord_read.TOOLS

    if ctx.guild and ctx.requester and ctx.bot.get_cog("PlayerCog") is not None:
        tools += music.TOOLS

    if ctx.guild and actions.can_move_members(ctx):
        tools.append(actions.voice_kick)
        in_voice = ctx.requester.voice and ctx.requester.voice.channel
        if in_voice and ctx.bot.get_cog("CountdisCog") is not None:
            tools.append(actions.voice_disconnect_timer)

    if ctx.guild and ctx.requester and reminders.scheduler_for(ctx) is not None:
        tools += reminders.TOOLS

    return tools


def status_line(name: str, args: dict) -> str:
    """The persona status shown while a tool runs; empty when it needs none."""
    make = _STATUS.get(name)
    return make(args) if make else ""
