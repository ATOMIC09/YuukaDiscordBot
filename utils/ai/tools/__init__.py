"""
utils/ai/tools/__init__.py
The tools Yuuka may use, picked per turn.
"""

from __future__ import annotations

from typing import Callable

from langchain_core.tools import BaseTool

from utils.ai.context import YuukaContext
from utils.ai.tools import (
    actions, attendance, capture, discord_read, memory, music, reminders, search, server, wait,
)

# Tools that only look something up. The same call twice in one reply would return the
# same thing, so the agent runs it once. Never put an action here: "play X" twice is a
# real request, and removing queue position 2 twice removes two songs.
READ_ONLY = frozenset({
    "web_search", "read_messages", "search_messages",
    "voice_members", "user_info", "server_info",
    "music_now_playing", "music_queue", "music_history",
    "memory_search",
})

# Tools whose arguments are a server's private notes. The agent keeps them out of its log
# lines, and the log file outlives the reply.
PRIVATE_ARGS = frozenset(tool.name for tool in memory.TOOLS)

_STATUS: dict[str, Callable[[dict], str]] = {
    **search.STATUS,
    **discord_read.STATUS,
    **server.STATUS,
    **music.STATUS,
    **actions.STATUS,
    **attendance.STATUS,
    **capture.STATUS,
    **reminders.STATUS,
    **memory.STATUS,
    **wait.STATUS,
}


def tools_for(ctx: YuukaContext) -> list[BaseTool]:
    """Only the tools that can work this turn, which also keeps the prompt short."""
    tools: list[BaseTool] = [*search.TOOLS]

    if ctx.guild and ctx.requester:
        # What these return is filtered by what the requester can see, so
        # there has to be one (a reaction reply has none).
        tools += server.TOOLS + discord_read.TOOLS

    if ctx.guild and ctx.requester and ctx.bot.get_cog("PlayerCog") is not None:
        # Waiting only makes sense between actions, and music is where they chain.
        tools += music.TOOLS + wait.TOOLS

    if ctx.guild and ctx.requester:
        # Offered even when the requester could not use them (no permission, not in
        # voice): the tool refuses with the reason and the model relays it. Hiding
        # them left the model with nothing to call, so she claimed to have done it.
        tools.append(actions.voice_kick)
        if ctx.bot.get_cog("CountdisCog") is not None:
            tools.append(actions.voice_disconnect_timer)

    if ctx.guild and ctx.requester and ctx.bot.get_cog("AttendanceCog") is not None:
        # Like the kick tool: offered to anyone, and refused with the reason when the
        # requester is not in a voice channel.
        tools += attendance.TOOLS

    if ctx.guild and ctx.requester:
        # Starting one proposes and asks for confirmation; both refuse with the reason
        # when the requester is not in a voice channel.
        if ctx.bot.get_cog(capture.RECORD_COG) is not None:
            tools += capture.RECORD_TOOLS
        if ctx.bot.get_cog(capture.CAPTION_COG) is not None:
            tools += capture.CAPTION_TOOLS

    if ctx.guild and ctx.requester and reminders.scheduler_for(ctx) is not None:
        tools += reminders.TOOLS

    if ctx.guild and ctx.requester and (store := memory.store_for(ctx)) is not None:
        # Saving is offered before /memory setup too: it refuses with the reason. Hiding it
        # left the model to say "ok, I will remember" without calling anything.
        tools.append(memory.memory_save)
        if store.channel_for(ctx.guild) is not None:
            tools += [memory.memory_search, memory.memory_forget]

    return tools


def status_line(name: str, args: dict) -> str:
    """The persona status shown while a tool runs; empty when it needs none."""
    make = _STATUS.get(name)
    return make(args) if make else ""
