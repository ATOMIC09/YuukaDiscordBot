"""
utils/wake_acoustic.py
Acoustic pre-filter for /ai voice: decides whether a closed speech segment is
worth transcribing at all, ahead of utils/wake.py's text match.

Why a pre-filter and not the trigger itself
--------------------------------------------
The shipped model (yuuka_wakeword_v2, see wakeword_training/TRAINING.md) is
used as a cheap gate, not a trigger. It ran at about 87% recall and 43 false
accepts/hour on its held-out set, scored one clip at a time; nobody has measured
it on real Discord voices yet. A gate with that profile is fine
for a "is this worth paying for STT" gate — a false accept just costs one
wasted transcription that utils/wake.py's text match silently drops. It would
not be fine as the sole trigger: the LLM would end up answering unrelated
conversation every couple of minutes.

The threshold that buys those numbers is model-specific, not a constant, so
re-derive it with wakeword_training/compare_models.py after any promotion —
the same number means a different operating point on a different model.

Why every 80 ms hop, including for short segments
---------------------------------------------------
The classifier reads the last 16 speech embeddings (~2 s), and it was trained
on clips with the word at the *end* of that window (speech ends at 1.7-2.0 s of
2.0 s). It scores high only when the word sits at the window's trailing edge,
and drops fast when it sits earlier. openWakeWord therefore scores every 80 ms
hop. An earlier version of this module scored 2 s windows at a 1 s stride, so
a word was seen at the right offset only by luck: on synthetic "Yuuka, <speech>"
segments that gave a median 0.05 against 0.23 at 80 ms, and a "miss" there is
a silent drop of a real summon.

A segment of 2 s or less used to get a single window, ending at its last sample,
which is every bare "Yuuka". Discord keeps sending audio after the speaker stops
(longer while music or noise holds the mic open), so the word was no longer at the
trailing edge and scored near zero. The segment now gets a full window of silence
in front, rounded up to a whole number of hops, so a window ends at every 80 ms of
it, wherever the word ended. The last window is the one the old code scored, so a
score can only go up; the price is that more segments reach STT, which the
threshold has to account for (config.py).

Scoring every hop is cheap here: the mel spectrogram and the embeddings are
computed once for the whole segment, and only the small classifier runs per hop
(the same 76-frame window / 8-frame stride WakeWordModel.predict uses). This
reaches into WakeWordModel's private frontends, because its public predict()
only returns the tail window; recheck it after a livekit-wakeword upgrade.

Comparing two models
--------------------
STT_WAKE_ACOUSTIC_COMPARE_PATH (dev only, empty in production) loads a second
classifier that is run on the same windows and only logged, so one test session
compares two models on identical audio. It shares the mel and embedding work,
which is most of the cost, and never decides the gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NamedTuple

import numpy as np

from bot.config import config
from bot.logger import logger
from utils.audio import pcm_to_mono16k

_SAMPLE_RATE = 16_000
_WINDOW_SAMPLES = 2 * _SAMPLE_RATE  # one classifier window: 16 embeddings, about 2 s
_HOP_SAMPLES = 1_280  # one embedding step: 8 mel frames of 10 ms, i.e. 80 ms
_MIN_EMBEDDINGS = 16  # classifier input length


class _Scores(NamedTuple):
    """One model's scores for one segment, as logged."""

    best: float  # best window: what the gate compares to the threshold
    at_end: float  # the window ending at the last sample, all the old scoring looked at
    before_end: float  # seconds from the best window's end to the segment's end

    @classmethod
    def of(cls, scores: np.ndarray) -> "_Scores":
        best = int(np.argmax(scores))
        before_end = (len(scores) - 1 - best) * _HOP_SAMPLES / _SAMPLE_RATE
        return cls(float(scores[best]), float(scores[-1]), before_end)

    def describe(self) -> str:
        return (
            f"best {self.best:.3f} on the window ending {self.before_end:.2f}s before the "
            f"segment end, end window alone {self.at_end:.3f}"
        )


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
        self._name = ""
        self._compare: tuple | None = None  # (onnx session, input name), logged only
        self._compare_name = ""
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
            self._name = model_path.stem
            logger.info(f"[Wake Acoustic] Loaded model from {model_path}")
        except Exception as exc:
            logger.warning(f"[Wake Acoustic] Failed to load model: {exc}")
            return

        if config.stt_wake_acoustic_compare_path:
            self._load_compare(Path(config.stt_wake_acoustic_compare_path))

    def _load_compare(self, path: Path) -> None:
        """Load the dev-only comparison classifier, the same way WakeWordModel loads one."""
        if not path.exists():
            logger.warning(f"[Wake Acoustic] Comparison model not found at {path}, not comparing")
            return
        try:
            import onnxruntime as ort

            session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self._compare = (session, session.get_inputs()[0].name)
            self._compare_name = path.stem
            logger.info(f"[Wake Acoustic] Also scoring with {path} (logged only, never decides)")
        except Exception as exc:
            logger.warning(f"[Wake Acoustic] Failed to load comparison model: {exc}")

    def _predict_max(self, audio: np.ndarray) -> tuple[_Scores, _Scores | None, int]:
        """Score a window ending at every 80 ms hop of ``audio``.

        Returns the gate model's scores, the comparison model's (None when there is
        none), and how many windows were scored.
        """
        assert self._model is not None
        model = self._model

        # A full window of silence in front, rounded up so the padded length is a whole
        # number of hops: the last window then ends exactly at the segment's last sample
        # (the one window the old code scored) and every earlier hop ends a window too.
        lead = _WINDOW_SAMPLES + (-audio.size) % _HOP_SAMPLES
        audio = np.concatenate(
            [np.zeros(lead, dtype=np.float32), audio.astype(np.float32, copy=False)]
        )

        mel = model._mel_frontend(audio)
        embeddings = model._speech_embedding.extract_embeddings(mel)[0]
        if embeddings.shape[0] < _MIN_EMBEDDINGS:
            return _Scores(0.0, 0.0, 0.0), None, 0

        n = embeddings.shape[0] - _MIN_EMBEDDINGS + 1
        batch = np.stack(
            [embeddings[i : i + _MIN_EMBEDDINGS] for i in range(n)], axis=0
        ).astype(np.float32)

        scores = np.zeros(n, dtype=np.float32)
        for session, input_name in model._classifiers.values():
            scores = np.maximum(scores, session.run(None, {input_name: batch})[0][:, 0])

        compare = None
        if self._compare is not None:
            session, input_name = self._compare
            compare = _Scores.of(session.run(None, {input_name: batch})[0][:, 0])
        return _Scores.of(scores), compare, n

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

        scores, compare, windows = await asyncio.to_thread(self._predict_max, audio)
        # "end window alone" is what the old single-window scoring gave a segment of 2 s or
        # less: a best well above it means this segment would have been dropped before.
        line = f"[Wake Acoustic] {self._name}: {scores.describe()} ({windows} windows)"
        if compare is not None:
            line += f" | {self._compare_name} (logged only): {compare.describe()}"
        logger.debug(line)
        return scores.best >= config.stt_wake_acoustic_threshold, scores.best


# Singleton — import this object everywhere, mirroring utils/wake.py's module
# functions.
acoustic_wake = AcousticWakeDetector()
