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

Earlier talk before the name
----------------------------
In a call people talk without 800 ms of quiet, so a segment is often earlier
chatter and then "Yuuka, ...". Transcribing all of it costs STT time and sends the
chatter to the model as if it were the request. The best window says where the
name ended, so the segment is cut at the last pause before it and only that phrase
goes to STT (`AcousticResult.cut`). Two things mark a pause: a stretch where the
speaker's client sent no packets (`SpeechSegment.pauses`: the audio simply has no gap
there) and a quiet stretch inside the audio. A cut is only kept if the model still
hears the name in what is left, so a pause inside the name cannot chop it.
Nothing is cut without a pause (no pause found means the whole segment, as before),
and a request said just before the name with a pause between them is cut too: the
chime still sounds and she listens for it again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np

from bot.config import config
from bot.logger import logger
from utils.audio import BYTES_PER_FRAME, OPUS_SAMPLE_RATE, TARGET_SAMPLE_RATE, pcm_to_mono16k, quiet_stretches

_SAMPLE_RATE = 16_000
_WINDOW_SAMPLES = 2 * _SAMPLE_RATE  # one classifier window: 16 embeddings, about 2 s
_HOP_SAMPLES = 1_280  # one embedding step: 8 mel frames of 10 ms, i.e. 80 ms
_MIN_EMBEDDINGS = 16  # classifier input length
# Bytes of the hub's 48 kHz stereo PCM that make one sample of the 16 kHz mono audio.
_BYTES_PER_SAMPLE_16K = BYTES_PER_FRAME * (OPUS_SAMPLE_RATE // TARGET_SAMPLE_RATE)

# A speaker's client stops sending while they are quiet, so a pause shorter than the
# segment gap leaves no silence in the segment at all (see SpeechSegment.pauses). The
# model was trained on a word that follows silence, so it is put back for scoring: this
# much of it at most, as that is all the context the model reads.
_RESTORE_MAX_S = 0.6

# Cutting earlier talk off the front of a segment.
_TRIM_MIN_GAP_S = 0.3  # packets missing this long is a pause (the client's silence frames add ~0.1 s)
_TRIM_MIN_QUIET_S = 0.4  # a quiet stretch in the audio this long is a pause
_TRIM_KEEP_QUIET_S = 0.3  # of a quiet stretch, keep this much before the speech so no onset is clipped
_TRIM_MIN_CUT_S = 1.0  # cutting less than this is not worth the risk
_TRIM_NAME_S = 0.3  # a cut lands at least this long before the name's window ends (shortest name)
_TRIM_MAX_TRIES = 4  # pauses tried, latest first; each costs one more scan of the shorter audio
_TRIM_KEEP_SCORE = 0.8  # what is left must still score this share of the whole segment's best
# A segment that did not pass as a whole may still hold the name after a pause. Looking costs
# a scan of the rest of the segment per pause, so only a segment the model found at least a
# little plausible gets it, and only its last few pauses.
_PHRASE_MIN_SCORE = 0.1
_PHRASE_MAX_TRIES = 2
# A segment with this much after the name holds a request too ("Yuuka, kick everyone"). Seen
# in real calls: a bare name ended 0.08-0.24 s before the segment end (the audio Discord sends
# after the speaker stops), a name with a request 1.0-3.4 s before it.
_ONESHOT_AFTER_S = 0.6


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


def _restore_pauses(
    audio: np.ndarray, markers: Sequence[tuple[int, float]]
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """`audio` with silence put back where the speaker's client stopped sending.

    `markers` are (sample, silent seconds) in `audio`, in order. Returns the audio and a
    block per marker: (start in the new audio, length, sample in the old one)."""
    pieces: list[np.ndarray] = []
    blocks: list[tuple[int, int, int]] = []
    previous = inserted = 0
    for sample, gap_s in markers:
        length = int(min(gap_s, _RESTORE_MAX_S) * _SAMPLE_RATE)
        if length <= 0 or not previous <= sample <= audio.size:
            continue
        pieces.append(audio[previous:sample])
        pieces.append(np.zeros(length, dtype=np.float32))
        blocks.append((sample + inserted, length, sample))
        inserted += length
        previous = sample
    if not blocks:
        return audio, []
    pieces.append(audio[previous:])
    return np.concatenate(pieces), blocks


def _original_sample(restored: int, blocks: Sequence[tuple[int, int, int]]) -> int:
    """Where a sample of the restored audio sits in the original (a pause maps to its marker)."""
    shift = 0
    for start, length, original in blocks:
        if restored >= start + length:
            shift += length
        elif restored >= start:
            return original
        else:
            break
    return restored - shift


@dataclass(frozen=True)
class AcousticResult:
    """What the gate made of one segment."""

    heard: bool  # worth transcribing
    score: float  # best window score
    cut: int = 0  # bytes to drop from the front of the segment's PCM before transcribing it
    scored: bool = True  # False when no model ran (disabled, or it failed to load): a free pass
    after_name: float = 0.0  # seconds of the segment after the window where the name was heard

    @property
    def confident(self) -> bool:
        """Sure enough that it was her name to say so before STT has read it."""
        return self.heard and self.scored and self.score >= config.stt_wake_acoustic_confident_score

    @property
    def oneshot(self) -> bool:
        """Something was said after the name, so the segment is likely a request with it."""
        return self.heard and self.scored and self.after_name >= _ONESHOT_AFTER_S


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

    def _predict_max(
        self, audio: np.ndarray, compare: bool = True
    ) -> tuple[_Scores, _Scores | None, int]:
        """Score a window ending at every 80 ms hop of ``audio``.

        Returns the gate model's scores, the comparison model's (None when there is
        none, or `compare` is False), and how many windows were scored.
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

        compared = None
        if compare and self._compare is not None:
            session, input_name = self._compare
            compared = _Scores.of(session.run(None, {input_name: batch})[0][:, 0])
        return _Scores.of(scores), compared, n

    @staticmethod
    def _pause_candidates(audio: np.ndarray, markers: Sequence[tuple[int, float]]) -> dict[int, str]:
        """Samples where a phrase could start: after a gap in the packets, or a quiet stretch."""
        candidates: dict[int, str] = {}
        for sample, gap_s in markers:
            if gap_s >= _TRIM_MIN_GAP_S:
                candidates[sample] = "packet"
        for start_s, end_s in quiet_stretches(audio, _TRIM_MIN_QUIET_S):
            cut_s = max(start_s + 0.1, end_s - _TRIM_KEEP_QUIET_S)
            candidates.setdefault(int(cut_s * _SAMPLE_RATE), "quiet")
        return candidates

    def _phrase_score(self, audio: np.ndarray, markers: Sequence[tuple[int, float]], cut: int) -> float:
        """Best score of the audio from `cut` on, scored as a phrase of its own."""
        rest, _ = _restore_pauses(audio[cut:], [(s - cut, g) for s, g in markers if s > cut])
        return self._predict_max(rest, compare=False)[0].best

    def _trim_start(
        self, audio: np.ndarray, markers: Sequence[tuple[int, float]], best: float, window_end_s: float
    ) -> tuple[int, str, float]:
        """Sample at which the audio for STT should start, to drop earlier talk.

        `markers` are (sample, silent seconds) where the speaker's client sent nothing and
        `window_end_s` is where the model heard the name end, both in `audio`. Returns
        (sample, what marked the pause, best score of what is left), or (0, "", 0.0) to
        keep the whole segment."""
        low = int(_TRIM_MIN_CUT_S * _SAMPLE_RATE)
        high = int((window_end_s - _TRIM_NAME_S) * _SAMPLE_RATE)
        if high < low:
            return 0, "", 0.0

        candidates = self._pause_candidates(audio, markers)
        usable = sorted((c for c in candidates if low <= c <= high), reverse=True)
        for cut in usable[:_TRIM_MAX_TRIES]:
            kept = self._phrase_score(audio, markers, cut)
            if kept >= max(config.stt_wake_acoustic_threshold, _TRIM_KEEP_SCORE * best):
                return cut, candidates[cut], kept
        return 0, "", 0.0

    def _phrase_hit(self, audio: np.ndarray, markers: Sequence[tuple[int, float]]) -> tuple[int, str, float]:
        """For a segment whose whole did not pass: a phrase after a pause that does.

        The name after earlier talk is read against that talk (it is inside the same 2 s
        window), and a person who has just been talking is the usual caller. Returns
        (sample the phrase starts at, what marked the pause, its score) or (0, "", 0.0)."""
        low = int(_TRIM_MIN_CUT_S * _SAMPLE_RATE)
        high = audio.size - int(_TRIM_NAME_S * _SAMPLE_RATE)
        candidates = self._pause_candidates(audio, markers)
        usable = sorted((c for c in candidates if low <= c <= high), reverse=True)
        for cut in usable[:_PHRASE_MAX_TRIES]:
            score = self._phrase_score(audio, markers, cut)
            if score >= config.stt_wake_acoustic_threshold:
                return cut, candidates[cut], score
        return 0, "", 0.0

    def _analyse(self, audio: np.ndarray, pauses: Sequence[tuple[int, float]]) -> AcousticResult:
        markers = sorted((offset // _BYTES_PER_SAMPLE_16K, gap) for offset, gap in pauses)
        restored, blocks = _restore_pauses(audio, markers)
        scores, compare, windows = self._predict_max(restored)
        heard = scores.best >= config.stt_wake_acoustic_threshold
        # "end window alone" is what the old single-window scoring gave a segment of 2 s or
        # less: a best well above it means this segment would have been dropped before.
        line = f"[Wake Acoustic] {self._name}: {scores.describe()} ({windows} windows"
        line += f", {len(blocks)} pause(s) put back)" if blocks else ")"
        if compare is not None:
            line += f" | {self._compare_name} (logged only): {compare.describe()}"
        logger.debug(line)

        cut = 0
        score = scores.best
        # Where the name sat, for the chime; unknown (0) when only a later phrase passed.
        after_name = scores.before_end if heard else 0.0
        if heard and config.stt_trim_before_name:
            end = restored.size - int(round(scores.before_end * _SAMPLE_RATE))
            window_end_s = _original_sample(end, blocks) / _SAMPLE_RATE
            sample, how, kept = self._trim_start(audio, markers, scores.best, window_end_s)
            if sample:
                cut = sample * _BYTES_PER_SAMPLE_16K
                logger.info(
                    f"[Wake Acoustic] Cut {sample / _SAMPLE_RATE:.1f}s of earlier talk off the front "
                    f"({how} pause), the name still scores {kept:.3f} (was {scores.best:.3f})"
                )
        elif config.stt_trim_before_name and scores.best >= _PHRASE_MIN_SCORE:
            sample, how, found = self._phrase_hit(audio, markers)
            if sample:
                heard, score, cut = True, found, sample * _BYTES_PER_SAMPLE_16K
                logger.info(
                    f"[Wake Acoustic] The name only shows once the first {sample / _SAMPLE_RATE:.1f}s are left "
                    f"out ({how} pause): the phrase after it scores {found:.3f}, the whole {scores.best:.3f}"
                )
        return AcousticResult(heard, score, cut, after_name=after_name)

    async def detect(self, pcm: bytes, pauses: Sequence[tuple[int, float]] = ()) -> AcousticResult:
        """
        Test one closed speech segment's raw PCM for the acoustic wake word.

        `pauses` are where the speaker's client stopped sending (`SpeechSegment.pauses`).
        ``heard`` is True whenever the detector is unavailable (disabled, or the model
        failed to load) so callers get today's behavior by default; ``scored`` says
        whether a model really ran.
        """
        if not self.available:
            return AcousticResult(True, 1.0, scored=False)

        audio = pcm_to_mono16k(pcm)
        if audio.size == 0:
            return AcousticResult(False, 0.0)

        return await asyncio.to_thread(self._analyse, audio, pauses)


# Singleton — import this object everywhere, mirroring utils/wake.py's module
# functions.
acoustic_wake = AcousticWakeDetector()
