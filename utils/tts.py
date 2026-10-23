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

import os
import tempfile

import aiohttp
import edge_tts

from bot.logger import logger

DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"

# One more try after a failure: Microsoft's service sometimes refuses the first handshake (403,
# a clock off by a few minutes). edge_tts corrects its clock from the answer, but its own second
# stream runs on the session that just closed, so the correction only helps the next call.
_ATTEMPTS = 2


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
    # NamedTemporaryFile with delete=False — we hand the path to FFmpeg, then
    # delete it ourselves in the playback `after=` callback.
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    for attempt in range(1, _ATTEMPTS + 1):
        # A connector of its own for every try: edge_tts opens a ClientSession for each stream
        # and that session closes the connector it was given, so a shared one is dead after its
        # first use ("Session is closed"). ThreadedResolver uses stdlib getaddrinfo, which works
        # reliably on Windows unlike c-ares/aiodns (installed by py-cord[speed]).
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        try:
            await edge_tts.Communicate(text, voice, connector=connector).save(tmp.name)
            break
        except Exception as exc:
            if attempt == _ATTEMPTS:
                os.unlink(tmp.name)
                raise
            logger.warning(f"[TTS] Attempt {attempt} failed ({type(exc).__name__}: {exc}), trying again")
        finally:
            await connector.close()

    logger.debug(f"[TTS] Synthesized {len(text)} chars → {tmp.name}")
    return tmp.name
