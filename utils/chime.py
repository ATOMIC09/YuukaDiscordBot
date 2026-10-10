"""
utils/chime.py
Short earcons for /ai voice: a rising "ding-dong" when Yuuka starts listening and a
falling one when she stops, whether she got a request or the window ran out. "got" is a
"tik-tik" on one note, for a request said together with her name when no chime sounded
before STT: by the time she has heard it, listening is already over, so neither a start
nor a stop fits.

Why synthesised and not a sound file or TTS
--------------------------------------------
The chime has to be the first thing that reaches the speaker after the wake word, so
nothing may sit in front of it. TTS is a network round trip and FFmpegPCMAudio spawns a
subprocess; this is a few KB of raw PCM built once at import and handed to
`discord.PCMAudio`, so playback starts on the next 20 ms frame. It also keeps a binary
asset out of the repo.
"""

from __future__ import annotations

import io
import weakref
from typing import Literal

import discord
import numpy as np

from bot.logger import logger
from utils.audio import music_mixer

_RATE = 48_000  # PCMAudio is 48 kHz stereo 16-bit, in 20 ms frames
_FRAME_BYTES = 3_840  # 20 ms of that

# (frequency Hz, length s[, decay]) per note, frequency 0 for a rest; volume is a
# fraction of full scale. It has to be heard over a room full of people talking, so it
# is loud for an earcon; the closing chime stays a step quieter because it only says
# "never mind".
# Silence ahead of the first note. A client opens the stream as the first packets
# arrive and clips the opening of a short sound; her TTS is spared only because
# ffmpeg takes a moment to start, which a chime built in memory does not.
_LEAD_IN_S = 0.15
# The very first transmission on a fresh connection loses even more: the client has
# not opened the stream yet. A client that has played nothing gets this longer lead-in
# once, after which `_WARM` remembers it. `warm_up` opens the stream ahead of time.
_COLD_LEAD_IN_S = 0.6

_WAKE = ([(880.0, 0.09), (1320.0, 0.15)], 0.70)
_DONE = ([(660.0, 0.09), (440.0, 0.15)], 0.50)
# The same note twice: neither rising (listening) nor falling (stopped), so "got it".
# Short and fast-decaying taps, so it cannot be heard as a slow ding.
_GOT = ([(1175.0, 0.06, 20.0), (0.0, 0.05), (1175.0, 0.12, 14.0)], 0.65)

_DECAY = 12.0  # how fast a note rings off, unless it says otherwise


def _render(notes: list[tuple[float, ...]], volume: float, lead_in: float = _LEAD_IN_S) -> bytes:
    parts = []
    for note in notes:
        freq, length, decay = note if len(note) == 3 else (*note, _DECAY)
        t = np.arange(int(_RATE * length)) / _RATE
        if not freq:
            parts.append(np.zeros_like(t))
            continue
        # Fast attack, exponential decay: a bell-like ding that rings off, no click at either end.
        envelope = np.minimum(t / 0.005, 1.0) * np.exp(-t * decay)
        envelope[-int(_RATE * 0.004) :] *= np.linspace(1.0, 0.0, int(_RATE * 0.004))
        parts.append(np.sin(2 * np.pi * freq * t) * envelope)
    mono = np.concatenate([np.zeros(int(_RATE * lead_in)), *parts]) * volume
    pcm = (np.repeat(mono, 2) * 32767).astype("<i2").tobytes()
    return pcm + b"\x00" * (-len(pcm) % _FRAME_BYTES)


_SOUNDS = {"wake": _render(*_WAKE), "done": _render(*_DONE), "got": _render(*_GOT)}
_COLD_SOUNDS = {
    "wake": _render(*_WAKE, lead_in=_COLD_LEAD_IN_S),
    "done": _render(*_DONE, lead_in=_COLD_LEAD_IN_S),
    "got": _render(*_GOT, lead_in=_COLD_LEAD_IN_S),
}
_SILENCE = bytes(_FRAME_BYTES * 20)  # 400 ms

# Voice clients that have already sent audio, so their stream is open on the listeners'
# side. Weak, so a client that goes away takes its entry with it.
_WARM: "weakref.WeakSet[discord.VoiceClient]" = weakref.WeakSet()


def mark_warm(voice_client: discord.VoiceClient | None) -> None:
    """Note that this client has sent audio (her speech does, as a chime does)."""
    if voice_client is not None:
        _WARM.add(voice_client)


def warm_up(voice_client: discord.VoiceClient | None) -> bool:
    """Open the stream with a moment of silence, so the first real sound is not clipped.

    Skipped when the client is busy or gone; a failure costs nothing but the warm-up."""
    if voice_client is None or not voice_client.is_connected():
        return False
    if voice_client.is_playing() or voice_client.is_paused():
        return False
    try:
        voice_client.play(discord.PCMAudio(io.BytesIO(_SILENCE)))
    except discord.ClientException:
        return False
    logger.debug("[Chime] Warming up the voice stream")
    return True


def play(voice_client: discord.VoiceClient | None, kind: Literal["wake", "done", "got"]) -> bool:
    """Start a chime and return at once. False when it could not play.

    One `VoiceClient` is shared with the music player and her own speech, and `play()`
    raises on a busy one. Over a playing track the chime is mixed into the track
    instead (`add_overlay`, the music ducks under it); against anything else, her own
    speech or a paused track, it is skipped rather than cut in."""
    if voice_client is None or not voice_client.is_connected():
        logger.info(f"[Chime] '{kind}' skipped: not connected to voice")
        return False
    if voice_client.is_playing() or voice_client.is_paused():
        mixer = music_mixer(voice_client)
        if mixer is None:
            logger.info(f"[Chime] '{kind}' skipped: the voice client is busy playing something")
            return False
        mixer.add_overlay(_SOUNDS[kind])
        logger.info(f"[Chime] '{kind}' playing over the music")
        return True
    try:
        cold = voice_client not in _WARM
        voice_client.play(discord.PCMAudio(io.BytesIO((_COLD_SOUNDS if cold else _SOUNDS)[kind])))
    except discord.ClientException as exc:
        # Lost a race with music or her own speech between the check and the call.
        logger.info(f"[Chime] '{kind}' skipped: {exc}")
        return False
    _WARM.add(voice_client)
    logger.info(f"[Chime] '{kind}' playing{' (first sound on this connection)' if cold else ''}")
    return True
