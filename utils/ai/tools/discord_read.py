"""
utils/ai/tools/discord_read.py
Read and search the messages of a channel in the requester's server.

Who may read a channel is decided by the REQUESTER's permissions, not the
bot's: the bot can usually see far more channels than the person asking, and
must not become a way around a channel they cannot open themselves.
"""

from __future__ import annotations

import discord
from langchain_core.tools import tool

from bot.logger import logger
from utils.ai.context import Ctx, YuukaContext
from utils.ai.tools.resolve import resolve_text_channel
from utils.errors import UserWarning

_MAX_CHARS = 8000
_MAX_LINE_CHARS = 500
_MAX_MATCHES = 10


async def _readable_channel(ctx: YuukaContext, name: str) -> discord.TextChannel | discord.Thread:
    # Resolving already refuses anything the requester cannot see at all,
    # private threads they are not in included.
    channel = await resolve_text_channel(ctx, name)
    if not channel.permissions_for(ctx.requester).read_message_history:
        # Say nothing about what the channel contains.
        raise UserWarning("อ่านช่องนั้นไม่ได้ค่ะ", "เซนเซย์ไม่มีสิทธิ์อ่านช่องนั้นนะคะ หนูเลยบอกอะไรไม่ได้ค่ะ")
    ctx.channels_used.append(channel)
    return channel


def _line(message: discord.Message) -> str:
    text = " ".join(message.clean_content.split())
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS] + "…"
    if message.attachments:
        files = ", ".join(a.filename for a in message.attachments)
        text = f"{text} [ไฟล์แนบ: {files}]".strip()
    stamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"[{stamp}] {message.author.display_name}: {text} <{message.jump_url}>"


def _source(ctx: YuukaContext, channel: discord.TextChannel | discord.Thread) -> str:
    # Spoken aloud, a mention would come out as its id digits: name it plainly.
    if ctx.voice:
        return f"#{channel.name}"
    # The mention renders as a clickable channel link in Discord. A "#name" she
    # writes instead is linked by utils.ai.linker.
    return f"{channel.mention} (#{channel.name}); cite it as {channel.mention} in your answer"


async def _history(channel, limit: int):
    try:
        async for message in channel.history(limit=limit):
            yield message
    except discord.Forbidden:
        raise UserWarning("อ่านช่องนั้นไม่ได้ค่ะ", "หนูเองก็ไม่มีสิทธิ์อ่านช่องนั้นเหมือนกันค่ะ (´-ω-`)")


@tool
async def read_messages(channel: str, ctx: Ctx, limit: int = 50) -> str:
    """Read the most recent messages of a text channel in this server.

    `channel` is a channel name, mention or id. `limit` is how many recent
    messages to read (1-100). Use it to answer questions about, or summarise,
    what was said in a channel. Messages from bots are skipped.
    """
    target = await _readable_channel(ctx, channel)
    limit = max(1, min(limit, 100))

    messages = [m async for m in _history(target, limit) if not m.author.bot]
    if not messages:
        return f"No messages from people in #{target.name}."

    lines = [_line(m) for m in reversed(messages)]  # oldest first
    dropped = 0
    while len(lines) > 1 and sum(len(x) + 1 for x in lines) > _MAX_CHARS:
        lines.pop(0)  # keep the newest
        dropped += 1

    logger.info(f"[AI Tools] read_messages #{target.name}: {len(lines)} messages for {ctx.requester}")
    header = f"{_source(ctx, target)}, oldest first"
    if dropped:
        header += f" ({dropped} older messages left out to fit)"
    return header + "\n" + "\n".join(lines)


@tool
async def search_messages(query: str, channel: str, ctx: Ctx, limit: int = 500) -> str:
    """Find messages containing some text in a text channel in this server.

    Case-insensitive substring match over the last `limit` messages (1-1000)
    of the channel. Returns up to 10 matches, newest first, with links.
    """
    target = await _readable_channel(ctx, channel)
    limit = max(1, min(limit, 1000))
    needle = query.casefold()

    checked = 0
    matches: list[discord.Message] = []
    async for message in _history(target, limit):
        if message.author.bot:
            continue
        checked += 1
        if needle in message.clean_content.casefold():
            matches.append(message)
            if len(matches) == _MAX_MATCHES:
                break

    logger.info(f"[AI Tools] search_messages '{query}' in #{target.name}: {len(matches)} hits for {ctx.requester}")
    if not matches:
        return f"No message in #{target.name} contains '{query}' (checked {checked} messages)."
    return (
        f"{len(matches)} match(es) in {_source(ctx, target)}, newest first:\n"
        + "\n".join(_line(m) for m in matches)
    )


def _read_status(args: dict) -> str:
    return f"<a:AppleLoadingGIF:1052465926487953428> กำลังอ่าน {args.get('channel', '')}..."


def _search_status(args: dict) -> str:
    return (
        f"<a:MagnifierGIF:1052563354910216252> กำลังค้นหา \"{args.get('query', '')}\" "
        f"ใน {args.get('channel', '')}..."
    )


TOOLS = [read_messages, search_messages]
STATUS = {"read_messages": _read_status, "search_messages": _search_status}
