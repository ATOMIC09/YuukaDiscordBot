"""
utils/ai/context.py
Everything a tool needs to know about the turn it is running in.

Tools receive this through `InjectedToolArg`, so the model never sees it in a
tool's schema and cannot fill it in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import discord


@dataclass
class YuukaContext:
    bot: discord.Bot
    guild: discord.Guild | None
    # Whose message started the turn. None means nobody can be acted on behalf
    # of (a reaction reply, an unresolved voice speaker), so no action tools.
    requester: discord.Member | None
    # Where the turn happens; the fallback channel for embeds.
    channel: discord.abc.Messageable
    voice: bool = False
    # Called by an action tool just before it acts, with an optional extra line.
    # Text: flush the streamed reply so it lands before the command embed.
    # Voice: speak the extra line, then wait for queued speech to finish.
    before_action: Callable[[str], Awaitable[None]] | None = None
