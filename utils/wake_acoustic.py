"""
utils/wake_acoustic.py
Acoustic pre-filter for /ai voice: decides whether a closed speech segment is
worth transcribing at all, ahead of utils/wake.py's text match.

Why a pre-filter and not the trigger itself
--------------------------------------------
The shipped model (see wakeword_training/TRAINING.md) is a proof-of-concept:
about 91 false triggers/hour at 80% recall. That is fine for a "is this worth
paying for STT" gate — a false accept just costs one wasted transcription that
utils/wake.py's text match silently drops. It would not be fine as the sole
trigger: the LLM would end up answering unrelated conversation roughly every
40 minutes.

Why a sliding window
---------------------
WakeWordModel.predict() only looks at the tail ~2 seconds of whatever chunk
it is given (it keeps the last 16 embeddings, taken at an 8-frame stride), so
handing it a whole long utterance in one call would miss a wake word spoken at
the start. utils/wake.py's text match has no such limit (head_chars=0 by
default matches anywhere in the utterance), so a segment is windowed across
its full length here too rather than just checking the tail.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from bot.config import config
from bot.logger import logger
from utils.audio import pcm_to_mono16k

_SAMPLE_RATE = 16_000
_WINDOW_S = 2.0
_STRIDE_S = 1.0
_WINDOW_SAMPLES = int(_WINDOW_S * _SAMPLE_RATE)
_STRIDE_SAMPLES = int(_STRIDE_S * _SAMPLE_RATE)


class AcousticWakeDetector:
    """
    Lazily-loaded wrapper around livekit.wakeword.WakeWordModel.

    Loading is deferred to first use (not import time) so a bot process that
    never enables the feature, or is missing the gitignored .onnx file, never
    pays for the import. A failed load disables the detector permanently
    rather than raising — callers fail open (treat every segment as a hit,
    i.e. behave exactly as if this module didn't exist) so a missing model
    file degrades to today's "always transcribe" behavior, not a crash.
    """

    def __init__(self) -> None:
        self._model = None
        self._load_attempted = False

    @property
    def available(self) -> bool:
        self._ensure_loaded()
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True

        if not config.stt_wake_acoustic_enabled:
            return

        model_path = Path(config.stt_wake_acoustic_model_path)
        if not model_path.exists():
            logger.warning(
                f"[Wake Acoustic] Model not found at {model_path}, acoustic "
                "gating disabled (falling back to always transcribing)."
            )
            return

        try:
            from livekit.wakeword import WakeWordModel

            self._model = WakeWordModel(models=[str(model_path)])
            logger.info(f"[Wake Acoustic] Loaded model from {model_path}")
        except Exception as exc:
            logger.warning(f"[Wake Acoustic] Failed to load model: {exc}")

    @staticmethod
    def _windows(audio: np.ndarray) -> list[np.ndarray]:
        if audio.size < _WINDOW_SAMPLES:
            pad = _WINDOW_SAMPLES - audio.size
            return [np.pad(audio, (pad, 0))]

        windows = []
        start = 0
        while start + _WINDOW_SAMPLES <= audio.size:
            windows.append(audio[start : start + _WINDOW_SAMPLES])
            start += _STRIDE_SAMPLES

        # The stride loop above may not land exactly on the tail — make sure
        # the last WINDOW_SAMPLES of the segment always gets its own check.
        tail_start = audio.size - _WINDOW_SAMPLES
        if tail_start % _STRIDE_SAMPLES != 0:
            windows.append(audio[tail_start:])
        return windows

    def _predict_max(self, windows: list[np.ndarray]) -> float:
        assert self._model is not None
        best = 0.0
        for window in windows:
            scores = self._model.predict(window)
            if scores:
                best = max(best, max(scores.values()))
        return best

    async def detect(self, pcm: bytes) -> tuple[bool, float]:
        """
        Test one closed speech segment's raw PCM for the acoustic wake word.

        Returns (heard, score). ``heard`` is True whenever the detector is
        unavailable (disabled, or the model failed to load) so callers get
        today's behavior by default.
        """
        if not self.available:
            return True, 1.0

        audio = pcm_to_mono16k(pcm)
        if audio.size == 0:
            return False, 0.0

        windows = self._windows(audio)
        score = await asyncio.to_thread(self._predict_max, windows)
        return score >= config.stt_wake_acoustic_threshold, score


# Singleton — import this object everywhere, mirroring utils/wake.py's module
# functions.
acoustic_wake = AcousticWakeDetector()
