"""
utils/ai/tools/__init__.py
The tools Yuuka may use, picked per turn.
"""

from __future__ import annotations

from typing import Callable

from langchain_core.tools import BaseTool

from utils.ai.context import YuukaContext
from utils.ai.tools import discord_read, music, search, server

_STATUS: dict[str, Callable[[dict], str]] = {
    **search.STATUS,
    **discord_read.STATUS,
    **server.STATUS,
    **music.STATUS,
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

    return tools


def status_line(name: str, args: dict) -> str:
    """The persona status shown while a tool runs; empty when it needs none."""
    make = _STATUS.get(name)
    return make(args) if make else ""
