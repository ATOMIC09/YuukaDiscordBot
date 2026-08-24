"""
bot/config.py
Loads environment variables from .env and exposes a typed Config dataclass.
Import the singleton `config` object — never access os.environ directly elsewhere.

OpenRouter settings use the `OPENROUTER_*` env var prefix.
Legacy `OLLAMA_*` vars are left in .env for optional local Ollama use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Typed configuration loaded from environment variables."""

    bot_token: str
    openrouter_api_key: str
    openrouter_model: str
    openrouter_system_prompt: str
    max_history_length: int
    tavily_api_key: str
    search_cache_ttl_minutes: int
    owner_id: int | None = None
    log_channel_id: int | None = None
    feedback_channel_id: int | None = None
    guild_ids: list[int] = field(default_factory=list)
    log_level: str = "INFO"

    # ── Speech-to-text ────────────────────────────────────────────────────
    # Backend: "auto" uses Groq when GROQ_API_KEY is set and falls back to the
    # local model otherwise (and whenever a Groq call fails). Groq's free tier
    # runs whisper-large-v3-turbo, which is far better at Thai than anything
    # this CPU can host — see .agents/AGENTS.md.
    stt_backend: str = "auto"          # auto | groq | local
    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"
    groq_timeout_s: float = 20.0

    # Local fallback (faster-whisper). "auto" picks small on CPU and
    # large-v3-turbo on CUDA. Any faster-whisper model name or a local
    # CTranslate2 model directory also works.
    stt_model: str = "auto"
    stt_device: str = "auto"           # auto | cpu | cuda
    stt_compute_type: str = "auto"     # auto | int8 | int8_float16 | float16 | float32
    # Which languages Whisper is allowed to decide on, e.g. "en,th,ja".
    # Empty = any of the ~100 it knows. One entry = hard lock, no detection.
    # Several = detection restricted to that shortlist, which stops a short
    # utterance from being read as an unrelated language.
    stt_languages: list[str] = field(default_factory=list)
    stt_beam_size: int = 5
    stt_cpu_threads: int = 0           # 0 = let CTranslate2 decide

    # ── Utterance segmentation ────────────────────────────────────────────
    # Discord clients run their own VAD and stop sending RTP packets when a
    # user is quiet, so "no packets for N ms" ends an utterance.
    stt_silence_ms: int = 800
    stt_min_segment_ms: int = 400
    stt_max_segment_s: int = 20
    stt_min_peak: float = 0.02         # reject segments quieter than this

    # ── Wake word gating (/ai voice only) ─────────────────────────────────
    stt_wake_words: list[str] = field(default_factory=list)
    stt_wake_threshold: int = 80       # rapidfuzz partial_ratio, 0-100
    stt_wake_head_chars: int = 0       # 0 = match the name anywhere; N = first N chars only
    stt_followup_window_s: int = 10    # keep listening to that speaker afterwards

    # ── Acoustic wake-word pre-filter (/ai voice only) ────────────────────
    stt_wake_acoustic_enabled: bool = True
    stt_wake_acoustic_model_path: str = "models/wake_word/yuuka_wakeword_v2.onnx"
    stt_wake_acoustic_threshold: float = 0.02

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config instance from environment variables. Raises if required values are missing."""
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN is not set. Copy .env.example to .env and fill in your token.")

        raw_guild_ids = os.getenv("GUILD_IDS", "")
        guild_ids = [int(g.strip()) for g in raw_guild_ids.split(",") if g.strip().isdigit()]

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Add your OpenRouter API key to .env."
            )

        openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/free")

        openrouter_system_prompt = os.getenv("OPENROUTER_SYSTEM_PROMPT")
        if not openrouter_system_prompt:
            raise ValueError(
                "OPENROUTER_SYSTEM_PROMPT is not set. Please add it to your .env file."
            )

        max_history_length = int(os.getenv("MAX_HISTORY_LENGTH", "50"))

        tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        search_cache_ttl_minutes = int(os.getenv("SEARCH_CACHE_TTL_MINUTES", "30"))

        log_channel_id_str = os.getenv("LOG_CHANNEL_ID")
        log_channel_id = int(log_channel_id_str) if log_channel_id_str and log_channel_id_str.isdigit() else None

        feedback_channel_id_str = os.getenv("FEEDBACK_CHANNEL_ID")
        feedback_channel_id = int(feedback_channel_id_str) if feedback_channel_id_str and feedback_channel_id_str.isdigit() else None

        owner_id_str = os.getenv("OWNER_ID")
        owner_id = int(owner_id_str) if owner_id_str and owner_id_str.isdigit() else None

        raw_wake = os.getenv(
            "STT_WAKE_WORDS", "ยูกะ,ยูคะ,ยุกะ,ยูกา,yuuka,yuka,yuuca,ゆうか,ゆか"
        )
        stt_wake_words = [w.strip() for w in raw_wake.split(",") if w.strip()]

        raw_langs = os.getenv("STT_LANGUAGE", "")
        stt_languages = [c.strip().lower() for c in raw_langs.split(",") if c.strip()]

        return cls(
            bot_token=token,
            guild_ids=guild_ids,
            log_level=log_level,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
            openrouter_system_prompt=openrouter_system_prompt,
            max_history_length=max_history_length,
            tavily_api_key=tavily_api_key,
            search_cache_ttl_minutes=search_cache_ttl_minutes,
            owner_id=owner_id,
            log_channel_id=log_channel_id,
            feedback_channel_id=feedback_channel_id,
            stt_backend=os.getenv("STT_BACKEND", "auto").strip().lower(),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "whisper-large-v3-turbo"),
            groq_timeout_s=float(os.getenv("GROQ_TIMEOUT_S", "20")),
            stt_model=os.getenv("STT_MODEL", "auto"),
            stt_device=os.getenv("STT_DEVICE", "auto"),
            stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "auto"),
            stt_languages=stt_languages,
            stt_beam_size=int(os.getenv("STT_BEAM_SIZE", "5")),
            stt_cpu_threads=int(os.getenv("STT_CPU_THREADS", "0")),
            stt_silence_ms=int(os.getenv("STT_SILENCE_MS", "800")),
            stt_min_segment_ms=int(os.getenv("STT_MIN_SEGMENT_MS", "400")),
            stt_max_segment_s=int(os.getenv("STT_MAX_SEGMENT_S", "20")),
            stt_min_peak=float(os.getenv("STT_MIN_PEAK", "0.02")),
            stt_wake_words=stt_wake_words,
            stt_wake_threshold=int(os.getenv("STT_WAKE_THRESHOLD", "80")),
            stt_wake_head_chars=int(os.getenv("STT_WAKE_HEAD_CHARS", "0")),
            stt_followup_window_s=int(os.getenv("STT_FOLLOWUP_WINDOW_S", "10")),
            stt_wake_acoustic_enabled=os.getenv("STT_WAKE_ACOUSTIC_ENABLED", "true").strip().lower()
            not in ("false", "0", "no"),
            stt_wake_acoustic_model_path=os.getenv(
                "STT_WAKE_ACOUSTIC_MODEL_PATH",
                "models/wake_word/yuuka_wakeword_v2.onnx",
            ),
            stt_wake_acoustic_threshold=float(os.getenv("STT_WAKE_ACOUSTIC_THRESHOLD", "0.02")),
        )


# Singleton — import this object everywhere
config = Config.from_env()
