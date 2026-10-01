"""
utils/ai/linker.py
Turn "#channel-name" in her streamed reply into a clickable channel mention.

The model is asked to cite a channel as <#id>, but it prefers the readable name,
which Discord shows as plain text. Only channels a tool used this turn are
linked: they were already resolved against what the requester can see.

The reply arrives in chunks, so a "#" whose name may still be growing is held
back until the next chunk (or the end of the reply) settles it.
"""

from __future__ import annotations

import re

import discord

from utils.ai.tools.resolve import channel_key

# A "#" and what may be a channel name after it. ASCII punctuation ends it; Thai
# has no spaces between words, so the name may also run straight into the text.
_TOKEN = re.compile(r"#([^\s#<>()\[\]{}*`'\",.!?;:|~]+)")
# Release a held "#" after this many characters even if it never ends.
_MAX_HOLD = 100


class ChannelLinker:
    def __init__(self, channels: list[discord.abc.GuildChannel]):
        # Shared with the turn's context: tools append to it while the reply streams.
        self._channels = channels
        self._buffer = ""

    def feed(self, text: str) -> str:
        """The part of the reply that is safe to show, linked."""
        self._buffer += text
        cut = len(self._buffer)
        start = self._buffer.rfind("#")
        if start != -1 and cut - start < _MAX_HOLD:
            match = _TOKEN.match(self._buffer, start)
            if (match is None and start == cut - 1) or (match is not None and match.end() == cut):
                cut = start
        out, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return self._link(out)

    def flush(self) -> str:
        out, self._buffer = self._buffer, ""
        return self._link(out)

    def _link(self, text: str) -> str:
        if not self._channels or "#" not in text:
            return text
        mentions = {channel_key(c.name): c.mention for c in self._channels}
        mentions.pop("", None)  # an all-emoji name would match anything
        return _TOKEN.sub(lambda m: _replace(m.group(1), mentions), text)


def _replace(token: str, mentions: dict[str, str]) -> str:
    # The longest start of the token that names a channel; the rest is ordinary text.
    for size in range(len(token), 0, -1):
        mention = mentions.get(channel_key(token[:size]) or None)
        if mention:
            return mention + token[size:]
    return "#" + token
