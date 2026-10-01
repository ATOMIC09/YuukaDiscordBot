"""
utils/ai/tools/music.py
Music control as tools. They run the same code as the /music commands through
`utils.ai_actions.run_action`, which also posts the embed that documents it.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from utils import ai_actions
from utils.ai.context import YuukaContext

Ctx = Annotated[YuukaContext, InjectedToolArg]


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

    `query` must be a song name or URL the user gave. Never make one up.
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


TOOLS = [music_play, music_skip, music_stop]

# The command embed already tells the user what is happening.
STATUS: dict = {}
