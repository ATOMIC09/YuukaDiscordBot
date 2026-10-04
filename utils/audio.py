"""
utils/audio.py
Raw-PCM helpers shared by the voice-receive pipeline.

Discord's Opus decoder hands us 48 kHz / 16-bit / stereo PCM (pycord hardcodes
this format). Whisper wants 16 kHz mono float32. Converting between the two is
the only real audio maths in the bot, so it lives here instead of being
re-derived in every module that touches a sink.
"""

from __future__ import annotations

import numpy as np

# Opus decoder output constants (pycord hardcoded values)
OPUS_SAMPLE_RATE = 48_000
OPUS_CHANNELS = 2
OPUS_SAMPLE_WIDTH = 2  # bytes — 16-bit signed little-endian
BYTES_PER_FRAME = OPUS_CHANNELS * OPUS_SAMPLE_WIDTH
BYTES_PER_SECOND = OPUS_SAMPLE_RATE * BYTES_PER_FRAME

# What Whisper expects
TARGET_SAMPLE_RATE = 16_000
_DECIMATION = OPUS_SAMPLE_RATE // TARGET_SAMPLE_RATE  # 3


def _lowpass_taps(num_taps: int = 31, cutoff_hz: float = 7_600.0) -> np.ndarray:
    """Windowed-sinc low-pass FIR, built once at import time."""
    fc = cutoff_hz / OPUS_SAMPLE_RATE  # normalised cutoff, cycles/sample
    n = np.arange(num_taps) - (num_taps - 1) / 2
    taps = np.sinc(2 * fc * n) * np.hamming(num_taps)
    return (taps / taps.sum()).astype(np.float32)


_TAPS = _lowpass_taps()


def pcm_to_mono16k(pcm: bytes) -> np.ndarray:
    """
    Convert 48 kHz stereo 16-bit PCM to the 16 kHz mono float32 array Whisper
    expects, scaled to [-1.0, 1.0].

    Decimating 48k→16k by simply keeping every third sample would fold
    everything above 8 kHz back down into the speech band, so the signal is
    low-passed first.

    We deliberately do NOT peak-normalise. On a near-silent segment that just
    amplifies the noise floor to full scale, which is a reliable way to make
    Whisper hallucinate a transcript out of room tone.
    """
    if not pcm:
        return np.zeros(0, dtype=np.float32)

    # Trim any partial frame — a truncated sample would flip channel parity
    # for the whole rest of the buffer.
    usable = len(pcm) - (len(pcm) % BYTES_PER_FRAME)
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)

    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768.0
    mono = samples.reshape(-1, OPUS_CHANNELS).mean(axis=1)

    if mono.size < _TAPS.size:
        # Too short to filter meaningfully; aliasing is moot at this length.
        return np.ascontiguousarray(mono[::_DECIMATION], dtype=np.float32)

    filtered = np.convolve(mono, _TAPS, mode="same")
    return np.ascontiguousarray(filtered[::_DECIMATION], dtype=np.float32)


def mono16k_to_wav(audio: np.ndarray) -> bytes:
    """
    Wrap a 16 kHz mono float32 array in a WAV container.

    Used to hand an utterance to a remote STT API. At 16 kHz mono a
    conversational utterance is a few hundred KB — far below any upload cap —
    so there is no reason to pay the CPU cost of compressing it first.
    """
    import io
    import wave

    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


async def decode_to_pcm(path: str) -> bytes:
    """Decode an audio file to 48 kHz stereo 16-bit PCM, all in memory.

    For her short spoken replies, so they can be mixed into the music stream."""
    import asyncio

    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", path,
        "-f", "s16le", "-ar", str(OPUS_SAMPLE_RATE), "-ac", str(OPUS_CHANNELS), "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore").strip())
    return stdout


def music_mixer(voice_client):
    """The music player's mixer on this voice client, if she can speak over it.

    Anything else playing (her own clip, nothing) or a paused track is None: a paused
    mixer is not read, so a sound added to it would never come out."""
    if voice_client is None or not voice_client.is_connected() or voice_client.is_paused():
        return None
    source = voice_client.source
    return source if hasattr(source, "add_overlay") else None


def boost_pcm(pcm: bytes, gain: float) -> bytes:
    """Make 16-bit PCM louder by `gain`, softening the peaks instead of clipping them.

    A plain multiply flat-tops any sample past full scale, which buzzes. tanh is
    linear for quiet samples and eases the loud ones toward the ceiling, so speech
    gets louder where it is quiet and nothing goes over."""
    if gain == 1.0 or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return (np.tanh(samples * gain) * 32767.0).astype(np.int16).tobytes()


def pcm_duration_seconds(pcm: bytes) -> float:
    """Wall-clock length of a 48 kHz stereo PCM buffer."""
    return len(pcm) / BYTES_PER_SECOND


def peak_amplitude(pcm: bytes) -> float:
    """
    Peak sample level in [0.0, 1.0].

    Used to throw away segments that are technically "speech" as far as
    Discord's client-side VAD is concerned but are really just a hot mic
    picking up a fan.
    """
    usable = len(pcm) - (len(pcm) % OPUS_SAMPLE_WIDTH)
    if usable <= 0:
        return 0.0
    samples = np.frombuffer(pcm[:usable], dtype="<i2")
    if samples.size == 0:
        return 0.0
    return float(np.abs(samples.astype(np.int32)).max()) / 32768.0
