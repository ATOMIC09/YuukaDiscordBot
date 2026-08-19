"""
utils/stt.py
Speech-to-Text with a remote primary and a local fallback.

Why not Typhoon ASR
-------------------
`scb10x/typhoon-asr-realtime` is a Thai-only FastConformer — its output
vocabulary is Thai, so English does not come out badly so much as come out as
Thai-script transliteration or noise. No amount of parameter tuning fixes
that; it needs a different model. Whisper is multilingual and handles the
Thai/English code-switching this server actually speaks ("เดี๋ยวหนู deploy
ให้นะคะ") inside a single utterance.

Why Groq is the primary
-----------------------
The deployment box is a 4-core i5-6500 with no GPU. Measured there, the
largest local model that keeps voice chat live (`small`) still gets the Thai
wake word wrong every time: it hears "ยูกะ" as "อยู่กับ", which collides
exactly with the ordinary Thai phrase "อยู่กับ…" — no confidence threshold can
separate a summons from "I was with friends". Models that *do* get it right
are 3-10x slower than realtime on that CPU.

Groq's free tier runs the real whisper-large-v3-turbo at roughly 20x realtime,
which fixes both problems at once. The local model stays as a fallback for a
missing key, a rate limit, or an outage, so voice never hard-fails — it just
gets worse.

Threading
---------
CTranslate2 models are not safe to call concurrently, so local inference runs
in a single-worker thread pool. Serialising also keeps CPU bounded when
several people talk at once. Requests are bounded by a semaphore: if a backlog
builds up, new segments are dropped rather than queued forever behind stale
audio nobody is waiting for any more.

Model loading
-------------
`ensure_loaded()` is awaitable and idempotent — the first call may download a
model, so callers should await it when a session starts rather than blocking
bot startup on it. With Groq configured there is nothing to download.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bot.config import config
from bot.logger import logger
from utils.audio import (
    TARGET_SAMPLE_RATE,
    mono16k_to_wav,
    pcm_duration_seconds,
    pcm_to_mono16k,
    peak_amplitude,
)

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
_load_lock = threading.Lock()
_model = None
_model_info: str = ""
_model_name: str = ""
_model_device: str = ""
_load_failed = False

# Kept alive for the process: dropping an os.add_dll_directory() handle is how
# you *un*register the directory again.
_cuda_dll_dirs: list = []

# At most this many segments may be waiting on the single inference worker.
# Voice is realtime — a transcript that arrives 30 seconds late is worse than
# no transcript, so we shed load instead of buffering it.
_MAX_PENDING = 3
_pending = asyncio.Semaphore(_MAX_PENDING)

# Whisper emits stock phrases when handed silence or noise. These are the ones
# that show up in practice; we drop them only when they are the *entire*
# transcript, so a genuine "ขอบคุณค่ะ" mid-sentence still survives.
_HALLUCINATIONS = {
    "ขอบคุณครับ",
    "ขอบคุณค่ะ",
    "ขอบคุณคะ",
    "สวัสดีครับ",
    "สวัสดีค่ะ",
    "โปรดติดตามตอนต่อไป",
    "แล้วพบกันใหม่",
    "thank you.",
    "thank you",
    "thanks for watching!",
    "thanks for watching",
    "you",
    "bye.",
    "bye",
    ".",
    "!",
    "?",
}


@dataclass(frozen=True)
class Transcript:
    """One transcribed utterance."""

    text: str
    language: str = ""
    language_probability: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.text)


def _groq_enabled() -> bool:
    """Whether the remote backend should be tried for this request."""
    if config.stt_backend == "local":
        return False
    if config.stt_backend == "groq":
        return bool(config.groq_api_key)
    return bool(config.groq_api_key)  # "auto"


def is_ready() -> bool:
    """True when at least one backend can transcribe."""
    return _groq_enabled() or _model is not None


def model_description() -> str:
    parts = []
    if _groq_enabled():
        parts.append(f"groq:{config.groq_model}")
    if _model is not None:
        parts.append(f"local:{_model_info}")
    return " + ".join(parts) or "not loaded"


def _resolve_settings() -> tuple[str, str, str]:
    """Turn the 'auto' config values into concrete faster-whisper arguments."""
    try:
        import ctranslate2
    except ImportError:
        ctranslate2 = None

    device = config.stt_device
    if device == "auto":
        try:
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"

    model = config.stt_model
    if model == "auto":
        # The deployment target is CPU-only, and the big models are not
        # realtime there: on a 4-core Skylake, large-v3-turbo takes longer to
        # transcribe an utterance than it took to say it. `small` is the
        # largest model that keeps voice chat feeling live. On a GPU there is
        # no reason to settle for it — large-v3-turbo is far better at Thai.
        model = "large-v3-turbo" if device == "cuda" else "small"

    # Never infer a compute type from the device alone. A card can report CUDA
    # and still have no usable float16 path (Pascal and older), and CTranslate2
    # then refuses to load rather than falling back — so ask what it supports.
    supported: set[str] = set()
    if ctranslate2 is not None:
        try:
            supported = set(ctranslate2.get_supported_compute_types(device))
        except Exception:
            supported = set()

    compute_type = config.stt_compute_type
    if compute_type != "auto":
        if supported and compute_type not in supported:
            logger.warning(
                f"[STT] STT_COMPUTE_TYPE='{compute_type}' is not supported on "
                f"{device} (available: {sorted(supported)}) — using auto instead."
            )
        else:
            return model, device, compute_type

    # Cheapest first: on CPU that is also the only one fast enough to matter.
    preference = (
        ["float16", "int8_float16", "int8_float32", "int8", "float32"]
        if device == "cuda"
        else ["int8", "int8_float32", "float32"]
    )
    for candidate in preference:
        if candidate in supported:
            return model, device, candidate

    return model, device, "int8"


def _register_cuda_dlls() -> None:
    """
    Put the pip-installed CUDA libraries on Windows' DLL search path.

    CTranslate2 bundles no CUDA runtime. It dlopens cublas64_12.dll and
    cudnn*64_9.dll the first time a GPU model actually *runs*, which is why a
    missing library shows up as a per-utterance transcription error long after
    the model reported itself loaded. The nvidia-* wheels drop those DLLs in
    site-packages/nvidia/<lib>/bin — a directory Windows never searches on its
    own — so register it here. Without this the only other fix is a
    system-wide CUDA toolkit install.
    """
    if _cuda_dll_dirs or sys.platform != "win32":
        return

    try:
        import nvidia  # namespace package created by the nvidia-*-cu12 wheels
    except ImportError:
        return

    for root in nvidia.__path__:
        for bin_dir in sorted(Path(root).glob("*/bin")):
            if not any(bin_dir.glob("*.dll")):
                continue
            _cuda_dll_dirs.append(os.add_dll_directory(str(bin_dir)))
            # add_dll_directory only covers loads that opt into the altered
            # search path; PATH covers the plain LoadLibrary calls that do not.
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    if _cuda_dll_dirs:
        logger.debug(f"[STT] Registered {len(_cuda_dll_dirs)} CUDA library directories")


def _load_cpu_fallback(model_name: str, reason: str) -> bool:
    """
    Rebuild the model on the CPU after CUDA turned out to be unusable.

    Returns True once the CPU model is live. Callers must hold `_load_lock`.
    """
    global _model, _model_info, _model_name, _model_device

    logger.warning(
        f"[STT] CUDA unusable ({reason}) — falling back to CPU. "
        "Set STT_DEVICE=cpu to skip this next time."
    )
    try:
        from faster_whisper import WhisperModel

        cpu_model = "small" if config.stt_model == "auto" else model_name
        _model = WhisperModel(
            cpu_model,
            device="cpu",
            compute_type="int8",
            cpu_threads=config.stt_cpu_threads,
        )
        _model_name = cpu_model
        _model_device = "cpu"
        _model_info = f"{cpu_model} / cpu / int8 (CUDA fallback)"
        logger.info(f"[STT] Ready — {_model_info}")
        return True
    except Exception as exc:
        logger.error(f"[STT] CPU fallback failed: {exc}")
        return False


def _is_cuda_failure(exc: Exception) -> bool:
    """Whether an inference error means "this GPU path will never work"."""
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("cublas", "cudnn", "cuda", "is not found or cannot be loaded")
    )


def _load_model_blocking() -> None:
    """Load the Whisper model once. Safe to call from multiple threads."""
    global _model, _model_info, _model_name, _model_device, _load_failed

    with _load_lock:
        if _model is not None or _load_failed:
            return

        _register_cuda_dlls()
        model_name, device, compute_type = _resolve_settings()
        logger.info(
            f"[STT] Loading faster-whisper '{model_name}' on {device.upper()} "
            f"({compute_type})… first run may download the model."
        )

        try:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=config.stt_cpu_threads,
            )
            _model_name = model_name
            _model_device = device
            _model_info = f"{model_name} / {device} / {compute_type}"
            logger.info(f"[STT] Ready — {_model_info}")
        except ImportError:
            _load_failed = True
            logger.error(
                "[STT] faster-whisper is not installed. Run `uv sync`. "
                "Transcription is disabled."
            )
        except Exception as exc:
            # A machine can report a CUDA device and still fail to load one —
            # missing cuBLAS/cuDNN libraries, a driver mismatch, no free VRAM.
            # Falling back to CPU keeps voice working (slower) instead of
            # disabling STT for the whole session.
            if device == "cuda" and _load_cpu_fallback(model_name, str(exc)):
                return

            _load_failed = True
            logger.error(f"[STT] Failed to load model: {exc}")


async def ensure_local_loaded() -> bool:
    """
    Load the local faster-whisper model if it isn't already.

    Runs on the inference executor so the event loop keeps serving Discord
    while a model downloads.
    """
    if _model is not None:
        return True
    if _load_failed:
        return False

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _load_model_blocking)
    return _model is not None


async def ensure_loaded() -> bool:
    """
    Make sure some backend can transcribe. Returns True once one can.

    With Groq configured there is nothing to load, so this returns immediately;
    the local model is only fetched if a Groq call later fails.
    """
    if _groq_enabled():
        return True
    return await ensure_local_loaded()


# Groq's verbose_json reports a language *name* where faster-whisper reports a
# code. Only the languages plausibly spoken (or mis-detected) in this server
# need an entry; anything else falls through unchanged.
_LANGUAGE_NAMES = {
    "english": "en", "thai": "th", "japanese": "ja", "chinese": "zh",
    "korean": "ko", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
    "lao": "lo", "khmer": "km", "burmese": "my", "tagalog": "tl",
    "hindi": "hi", "arabic": "ar", "russian": "ru", "spanish": "es",
    "french": "fr", "german": "de", "portuguese": "pt", "italian": "it",
}

_allowed_languages_cache: list[str] | None = None


def _normalize_language(value: str) -> str:
    """Turn whatever a backend reports into a Whisper language code."""
    value = value.strip().lower()
    return _LANGUAGE_NAMES.get(value, value)


def _allowed_languages() -> list[str]:
    """
    The configured language shortlist, minus codes Whisper does not know.

    Config is loaded once, so this is resolved once and cached — including the
    warning, which should not repeat on every utterance.
    """
    global _allowed_languages_cache
    if _allowed_languages_cache is not None:
        return _allowed_languages_cache

    codes = [_normalize_language(c) for c in config.stt_languages]
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES
    except ImportError:
        _allowed_languages_cache = codes
        return codes

    unknown = [c for c in codes if c not in _LANGUAGE_CODES]
    if unknown:
        logger.warning(
            f"[STT] Ignoring unknown STT_LANGUAGE entries: {unknown} — "
            "use ISO codes such as en, th, ja."
        )
    _allowed_languages_cache = [c for c in codes if c in _LANGUAGE_CODES]
    return _allowed_languages_cache


def _best_allowed(all_probs, allowed: list[str]) -> str:
    """Pick the shortlisted language the model considered most likely."""
    if all_probs:
        ranked = dict(all_probs)
        return max(allowed, key=lambda code: ranked.get(code, 0.0))
    return allowed[0]


def _transcribe_options() -> dict:
    """Decoding options shared by the first pass and any language retry."""
    return {
        "task": "transcribe",
        "beam_size": config.stt_beam_size,
        # Each utterance is independent — carrying context between them is
        # what makes Whisper fall into repetition loops on short clips.
        "condition_on_previous_text": False,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 300},
        "no_speech_threshold": 0.6,
        "log_prob_threshold": -1.0,
        "temperature": [0.0, 0.2, 0.4],
    }


def _run_transcribe(audio: np.ndarray, retry: bool = True) -> Transcript:
    """Blocking inference call. Runs on the single STT worker thread."""
    if _model is None:
        return Transcript("")

    try:
        allowed = _allowed_languages()
        # One configured language is a hard lock: skip detection entirely.
        forced = allowed[0] if len(allowed) == 1 else None
        options = _transcribe_options()

        segments, info = _model.transcribe(audio, language=forced, **options)

        # faster-whisper detects eagerly but decodes lazily, so an off-list
        # detection can be caught here, before the generator is consumed: the
        # wasted work is one encoder pass, not a whole transcript. A short
        # utterance is exactly where detection drifts to an unrelated
        # language, and the text that follows is then transliterated noise.
        if forced is None and allowed and info.language not in allowed:
            pick = _best_allowed(info.all_language_probs, allowed)
            logger.debug(
                f"[STT] Detected '{info.language}' "
                f"({info.language_probability:.2f}) is outside {allowed} — "
                f"re-running as '{pick}'"
            )
            segments, info = _model.transcribe(audio, language=pick, **options)

        text = "".join(seg.text for seg in segments).strip()

        if text.lower() in _HALLUCINATIONS:
            logger.debug(f"[STT] Dropped likely hallucination: {text!r}")
            return Transcript("", info.language, info.language_probability)

        return Transcript(text, info.language, info.language_probability)
    except Exception as exc:
        # A GPU model only touches cuBLAS/cuDNN on its first inference, so a
        # broken CUDA install lands here instead of at load time — where the
        # old code turned it into an empty transcript, once per utterance,
        # forever. Rebuild on the CPU and retry so the session recovers.
        if retry and _model_device == "cuda" and _is_cuda_failure(exc):
            with _load_lock:
                recovered = (
                    _model_device != "cuda"
                    or _load_cpu_fallback(_model_name, str(exc))
                )
            if recovered:
                return _run_transcribe(audio, retry=False)

        logger.error(f"[STT] Transcription error: {exc}")
        return Transcript("")


async def _transcribe_groq(audio: np.ndarray, force: str = "") -> Transcript | None:
    """
    Transcribe via Groq's OpenAI-compatible endpoint.

    Returns None — not an empty Transcript — when the request could not be
    completed, so the caller can tell "the API said there was no speech" apart
    from "the API was unreachable" and fall back only in the latter case.

    The endpoint takes a single language, not a shortlist, so a multi-language
    STT_LANGUAGE cannot be enforced up front the way it can locally. Instead
    the answer is checked afterwards, and an off-list one is re-requested with
    `force` set to the first configured language — the shortlist doubles as a
    priority order for exactly this case.
    """
    import aiohttp

    form = aiohttp.FormData()
    form.add_field("file", mono16k_to_wav(audio),
                   filename="utterance.wav", content_type="audio/wav")
    form.add_field("model", config.groq_model)
    form.add_field("response_format", "verbose_json")
    allowed = _allowed_languages()
    language_hint = force or (allowed[0] if len(allowed) == 1 else "")
    if language_hint:
        form.add_field("language", language_hint)

    try:
        timeout = aiohttp.ClientTimeout(total=config.groq_timeout_s)
        # ThreadedResolver for the same reason as bot.py and tts.py: aiodns
        # (pulled in by py-cord[speed]) fails DNS resolution on Windows.
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {config.groq_api_key}"},
                data=form,
            ) as resp:
                if resp.status == 429:
                    logger.warning("[STT] Groq rate limit hit — falling back to local")
                    return None
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    logger.warning(f"[STT] Groq HTTP {resp.status}: {body}")
                    return None
                payload = await resp.json()
    except asyncio.TimeoutError:
        logger.warning(f"[STT] Groq timed out after {config.groq_timeout_s}s")
        return None
    except Exception as exc:
        logger.warning(f"[STT] Groq request failed: {exc}")
        return None

    text = (payload.get("text") or "").strip()
    language = _normalize_language(payload.get("language") or "")

    if not force and allowed and language and language not in allowed:
        logger.debug(
            f"[STT] Groq answered in '{language}', outside {allowed} — "
            f"retrying as '{allowed[0]}'"
        )
        return await _transcribe_groq(audio, force=allowed[0])

    if text.lower() in _HALLUCINATIONS:
        logger.debug(f"[STT] Dropped likely hallucination: {text!r}")
        return Transcript("", language, 1.0)

    # verbose_json has no per-language confidence; the model is good enough
    # that treating a returned language as confident is fine.
    return Transcript(text, language, 1.0)


async def transcribe_pcm(pcm: bytes, user_display: str = "?") -> Transcript:
    """
    Transcribe one utterance of 48 kHz stereo 16-bit PCM (the format pycord's
    Opus decoder produces).

    Tries Groq first when configured and falls back to the local model if the
    request could not be completed. Returns an empty Transcript when no backend
    is available, the audio is too quiet or short to be speech, or the backlog
    is already full.
    """
    duration = pcm_duration_seconds(pcm)
    peak = peak_amplitude(pcm)
    if peak < config.stt_min_peak:
        logger.debug(f"[STT] {user_display}: skipped, peak {peak:.3f} below floor")
        return Transcript("")

    if _pending.locked():
        logger.warning(
            f"[STT] Backlog full ({_MAX_PENDING}) — dropping {duration:.1f}s "
            f"from {user_display}"
        )
        return Transcript("")

    audio = pcm_to_mono16k(pcm)
    if audio.size < TARGET_SAMPLE_RATE // 10:  # < 100 ms of samples
        return Transcript("")

    result: Transcript | None = None
    via = ""

    async with _pending:
        if _groq_enabled():
            result = await _transcribe_groq(audio)
            via = "groq"

        if result is None:
            # Either Groq is off, or the call failed. Load the local model on
            # demand — with Groq configured we never downloaded it up front.
            if config.stt_backend != "groq" and await ensure_local_loaded():
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(_executor, _run_transcribe, audio)
                via = "local"
            else:
                logger.warning(f"[STT] No backend available for {user_display}")
                return Transcript("")

    if result.text:
        logger.info(
            f"[STT] {user_display} ({result.language}, {duration:.1f}s, {via}): {result.text}"
        )
    else:
        logger.debug(f"[STT] {user_display}: (no speech detected in {duration:.1f}s)")

    return result
