"""
utils/wake_acoustic.py
Acoustic pre-filter for /ai voice: decides whether a closed speech segment is
worth transcribing at all, ahead of utils/wake.py's text match.

Why a pre-filter and not the trigger itself
--------------------------------------------
The shipped model (yuuka_wakeword_v2, see wakeword_training/TRAINING.md) runs
at about 87% recall and 43 false accepts/hour on its held-out set. That is fine
for a "is this worth paying for STT" gate — a false accept just costs one
wasted transcription that utils/wake.py's text match silently drops. It would
not be fine as the sole trigger: the LLM would end up answering unrelated
conversation every couple of minutes.

The threshold that buys those numbers is model-specific, not a constant, so
re-derive it with wakeword_training/compare_models.py after any promotion —
the same number means a different operating point on a different model.

Why every 80 ms hop
--------------------
The classifier reads the last 16 speech embeddings (~2 s), and it was trained
on clips with the word at the *end* of that window (speech ends at 1.7-2.0 s of
2.0 s). It scores high only when the word sits at the window's trailing edge,
and drops fast when it sits earlier. openWakeWord therefore scores every 80 ms
hop. An earlier version of this module scored 2 s windows at a 1 s stride, so
a word was seen at the right offset only by luck: on synthetic "Yuuka, <speech>"
segments that gave a median 0.05 against 0.23 at 80 ms, and a "miss" there is
a silent drop of a real summon.

Scoring every hop is cheap here: the mel spectrogram and the embeddings are
computed once for the whole segment, and only the small classifier runs per hop
(the same 76-frame window / 8-frame stride WakeWordModel.predict uses). This
reaches into WakeWordModel's private frontends, because its public predict()
only returns the tail window; recheck it after a livekit-wakeword upgrade.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from bot.config import config
from bot.logger import logger
from utils.audio import pcm_to_mono16k

_SAMPLE_RATE = 16_000
_MIN_SAMPLES = 2 * _SAMPLE_RATE  # 16 embeddings need about 2 s of audio
_MIN_EMBEDDINGS = 16  # classifier input length


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

    def _predict_max(self, audio: np.ndarray) -> float:
        """Best classifier score over every 16-embedding window of ``audio``."""
        assert self._model is not None
        model = self._model

        if audio.size < _MIN_SAMPLES:
            # Left-pad so the word, which ends the segment, stays at the end.
            audio = np.pad(audio, (_MIN_SAMPLES - audio.size, 0))

        mel = model._mel_frontend(audio)
        embeddings = model._speech_embedding.extract_embeddings(mel)[0]
        if embeddings.shape[0] < _MIN_EMBEDDINGS:
            return 0.0

        n = embeddings.shape[0] - _MIN_EMBEDDINGS + 1
        batch = np.stack(
            [embeddings[i : i + _MIN_EMBEDDINGS] for i in range(n)], axis=0
        ).astype(np.float32)

        best = 0.0
        for session, input_name in model._classifiers.values():
            out = session.run(None, {input_name: batch})[0]
            best = max(best, float(np.max(out[:, 0])))
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

        score = await asyncio.to_thread(self._predict_max, audio)
        return score >= config.stt_wake_acoustic_threshold, score


# Singleton — import this object everywhere, mirroring utils/wake.py's module
# functions.
acoustic_wake = AcousticWakeDetector()
