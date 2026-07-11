"""
cogs/voice/stt.py
Speech-to-Text provider using Typhoon ASR Real-Time.

Model: typhoon-ai/typhoon-asr-realtime (FastConformer-Transducer, 114M params)
Optimized for Thai language and CPU-first inference.

Usage
-----
Call `load_model()` once at bot startup (or let it lazy-load on first transcription).
Then call `transcribe_pcm(pcm_bytes, sample_rate, user_display)` from listener.py.

Architecture
------------
- Model is loaded once and reused (singleton pattern via module-level variable).
- Inference runs in a thread pool executor to avoid blocking the asyncio event loop.
- Audio from WaveSink is 16-bit stereo PCM at 48kHz; we write it to a temporary
  WAV file which the typhoon-asr package reads and resamples internally to 16kHz mono.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from bot.logger import logger

if TYPE_CHECKING:
    pass

# Module-level state
_model_loaded: bool = False
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
_transcribe_fn = None  # set after model load


def load_model(device: str = "cpu") -> None:
    """
    Load the Typhoon ASR model. Call once at startup.
    Safe to call multiple times — subsequent calls are no-ops.

    Args:
        device: "cpu" (default) or "cuda" if a GPU is available.
    """
    global _model_loaded, _transcribe_fn

    if _model_loaded:
        return

    logger.info(f"Loading Typhoon ASR model on {device.upper()}...")
    try:
        from typhoon_asr import transcribe as _typhoon_transcribe  # type: ignore[import]

        # Warm-up: import triggers model download on first run.
        # Store the function reference for later calls.
        _transcribe_fn = _typhoon_transcribe
        _model_loaded = True
        logger.info("Typhoon ASR ready")
    except ImportError:
        logger.error(
            "typhoon-asr is not installed. Run: uv add typhoon-asr\n"
            "STT transcription will be disabled."
        )


def _run_transcribe(wav_path: str) -> str:
    """
    Blocking transcription call — runs in a thread pool.
    Returns the transcript string (empty string on failure).
    """
    if _transcribe_fn is None:
        return ""
    try:
        result = _transcribe_fn(wav_path, device="cpu")
        return result.get("text", "").strip()
    except Exception as exc:
        logger.error(f"STT transcription error: {exc}")
        return ""


async def transcribe_wav_bytes(
    wav_bytes: io.BytesIO,
    user_display: str,
) -> str:
    """
    Transcribe audio from a BytesIO WAV file asynchronously.

    WaveSink produces 48kHz 16-bit stereo WAV. We write it to a temp file
    so typhoon-asr can read and resample it internally.

    Args:
        wav_bytes: BytesIO from sink.audio_data[user_id].file (already seeked to 0)
        user_display: Human-readable username string for logging

    Returns:
        Transcript text, or empty string if model not loaded / silence.
    """
    if not _model_loaded:
        logger.warning("STT model not loaded — skipping transcription for %s", user_display)
        return ""

    loop = asyncio.get_running_loop()

    # Write to a temp .wav file that typhoon-asr can open
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes.read())
        tmp_path = tmp.name

    transcript = await loop.run_in_executor(_executor, _run_transcribe, tmp_path)

    # Clean up temp file
    try:
        import os
        os.unlink(tmp_path)
    except OSError:
        pass

    if transcript:
        logger.info(f"[STT] {user_display}: {transcript}")
    else:
        logger.debug(f"[STT] {user_display}: (no speech detected)")

    return transcript
