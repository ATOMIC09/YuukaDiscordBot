"""
utils/tts.py
Async Edge TTS wrapper — synthesizes text to a temporary MP3 file.

Usage:
    mp3_path = await synthesize_speech("Hello!")
    # ... play mp3_path via discord.FFmpegPCMAudio ...
    os.unlink(mp3_path)   # caller is responsible for cleanup

Windows DNS note:
    aiodns (installed by py-cord[speed]) uses c-ares which fails DNS resolution
    on Windows. We pass aiohttp.TCPConnector(resolver=ThreadedResolver()) to
    edge_tts.Communicate — the same workaround used in bot/bot.py.
"""

from __future__ import annotations

import tempfile

import aiohttp
import edge_tts

from bot.logger import logger

DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"

# Lazily-created connector — ThreadedResolver uses stdlib getaddrinfo, which
# works reliably on Windows unlike c-ares/aiodns (installed by py-cord[speed]).
_connector: aiohttp.TCPConnector | None = None


async def synthesize_speech(text: str, voice: str = DEFAULT_VOICE) -> str:
    """
    Synthesize *text* to a temporary MP3 file using Edge TTS.

    Args:
        text:  The text to speak.
        voice: Edge TTS voice name. Defaults to en-US-EmmaMultilingualNeural.

    Returns:
        Absolute path to the generated MP3 file.
        **The caller is responsible for deleting the file after use.**
    """
    global _connector
    if _connector is None or _connector.closed:
        # Must be created inside a running event loop — do it lazily.
        _connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

    communicate = edge_tts.Communicate(text, voice, connector=_connector)

    # NamedTemporaryFile with delete=False — we hand the path to FFmpeg, then
    # delete it ourselves in the playback `after=` callback.
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    await communicate.save(tmp.name)
    logger.debug(f"[TTS] Synthesized {len(text)} chars → {tmp.name}")
    return tmp.name
