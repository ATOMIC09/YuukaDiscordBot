# Yuuka Discord Bot — Agent Knowledge Base

This document is the canonical reference for all agents working on this project.
Read this file before making any changes to understand the architecture, conventions, and patterns used.

---

## Project Overview

**Yuuka** is a Discord bot built with:
- **[py-cord](https://docs.pycord.dev/)** (`py-cord[speed,voice]>=2.8.0`) — Discord API wrapper (NOT `discord.py`)
- **[uv](https://astral.sh/uv)** — Python package & virtual environment manager
- **Python 3.12+**

The bot's primary features are:
1. **Application commands** — slash commands (`/command`) and context menus (right-click menus)
2. **AI chat** — stateful per-channel LLM conversations via OpenRouter
3. **Voice listening** — receive and process audio from users via pycord's sink API
4. **Voice transcription** — real-time STT using faster-whisper (multilingual Thai/English)
5. **AI voice chat** — wake-word-gated spoken conversation (`/ai voice`)

---

## Project Structure

```
YuukaDiscordBot/
├── main.py                   # Entry point: loads bot, auto-loads all cogs, runs
├── pyproject.toml            # uv project manifest
├── .env                      # Secrets (BOT_TOKEN, etc.) — NEVER commit this
├── .env.example              # Template for .env — ALWAYS keep updated
├── .python-version           # Python version pin for uv
│
├── bot/                      # Core bot package
│   ├── __init__.py
│   ├── bot.py                # Bot subclass (YuukaBot) — intents, event hooks, cog loader
│   ├── config.py             # Loads .env → typed Config dataclass
│   └── logger.py             # Loguru logger setup — import logger from here
│
├── cogs/                     # Feature cogs (auto-loaded by main.py)
│   ├── __init__.py
│   ├── ai/                   # AI chat feature
│   │   ├── __init__.py
│   │   └── chat.py           # /ai chat, /ai stop — stateful LLM chat sessions
│   ├── voice/                # Voice feature group
│   │   ├── __init__.py
│   │   ├── listener.py       # /record start, /record stop — saves Opus files
│   │   └── transcribe.py     # /transcribe start, /transcribe stop — live captions (no wake word)
│   ├── general/              # (empty — stub cogs removed; re-add when implementing)
│   │   └── __init__.py
│   └── moderation/           # (empty — stub cog removed; re-add when implementing)
│       └── __init__.py
│
├── utils/                    # Shared utilities (no Discord state — pure helpers)
│   ├── __init__.py
│   ├── checks.py             # Custom @commands.check() decorators
│   ├── embeds.py             # Embed builder factories
│   ├── errors.py             # Global on_application_command_error handler
│   ├── llm.py                # Async OpenRouter chat client (generate_chat_response)
│   ├── stt.py                # faster-whisper engine (ensure_loaded, transcribe_pcm)
│   ├── audio.py              # PCM helpers: 48k stereo → 16k mono float32
│   ├── wake.py               # Fuzzy wake-word gate (Thai/English tolerant)
│   └── voice_hub.py          # Single owner of voice receive; emits SpeechSegments
│
└── assets/
    └── audio/
        └── recordings/       # WAV files saved by listener.py (auto-created at runtime)
```

---

## Key Conventions & Patterns

### 1. Bot Subclass (`bot/bot.py`)
- The bot is an instance of `YuukaBot(discord.Bot)`.
- Use `discord.Bot` (NOT `commands.Bot`) since we use **slash/application commands only**.
- Required intents: `guilds`, `voice_states`, `message_content` (for the `on_message` listener in AI chat).
- `YuukaBot` is responsible for recursive cog loading via `load_cogs()`.

### 2. Cog Structure
Every cog file must follow this pattern:
```python
import discord
from discord.ext import commands
from bot.logger import logger

class MyCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

def setup(bot: discord.Bot):
    bot.add_cog(MyCog(bot))
```
- Cogs are **auto-discovered** by `main.py` — any `*.py` file under `cogs/` (excluding `__init__.py`) is loaded automatically.
- Do NOT manually register cogs in `main.py`.

### 3. Slash Commands
- Use `@discord.slash_command()` for slash commands.
- Use `@discord.user_command()` / `@discord.message_command()` for context menus.
- During **development**, pass `guild_ids=config.guild_ids` to sync commands instantly to test servers.
- In **production**, omit `guild_ids` for global command sync.

### 4. Config (`bot/config.py`)
- All secrets and settings are loaded from `.env` via `python-dotenv`.
- Access config via the singleton `config` object imported from `bot.config`.
- **Never** hardcode tokens, IDs, or secrets anywhere else.
- Key config values (all required unless noted):
  - `BOT_TOKEN` — Discord bot token
  - `GUILD_IDS` — comma-separated guild IDs for dev slash command sync
  - `LOG_LEVEL` — logging verbosity (`DEBUG`, `INFO`, `WARNING`) — default: `INFO`
  - `OLLAMA_BASE_URL` — OpenRouter base URL (e.g. `https://openrouter.ai/api/v1`)
  - `OLLAMA_MODEL` — OpenRouter model string (e.g. `google/gemini-2.5-flash-lite`)
  - `OLLAMA_SYSTEM_PROMPT` — system prompt injected at the start of every AI chat session

> **Note**: The config keys are named `OLLAMA_*` for historical reasons, but the LLM backend is now
> **OpenRouter** (not Ollama). The actual HTTP client in `utils/llm.py` targets the OpenRouter
> `/chat/completions` endpoint with an `Authorization: Bearer` header.

### 5. Logging (`bot/logger.py`)
- Uses **loguru** (`from loguru import logger`).
- All modules import the shared logger: `from bot.logger import logger`
- Do NOT use `print()` for debugging — use `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`.
- Log format includes timestamps, level, and the calling module.

### 6. Embeds (`utils/embeds.py`)
- All user-facing responses should use Discord embeds, not plain text.
- Use factory functions from `utils.embeds` to build consistent-looking embeds.
- Standard helpers: `success_embed`, `error_embed`, `info_embed`, `warning_embed`, `build_embed`.
- Standard color palette: success=green, error=red, info=blurple, warning=yellow.

### 7. Error Handling (`utils/errors.py`)
- A global `on_application_command_error` listener handles all unhandled exceptions.
- Individual cogs should **NOT** handle command validation failures by sending a plain message and returning. Instead, raise `UserError` or `UserWarning` (imported from `utils.errors`). The global error handler will catch this, log it properly (avoiding false "Command Execution" success logs), and send a formatted embed to the user.
- Never let raw tracebacks reach the user.

### 8. Persona & Tone (Yuuka)
- All user-facing text must be written in the persona of **Yuuka** (from Blue Archive).
- She refers to the user as "เซนเซย์" (Sensei) and herself as "หนู" (when polite/cute).
- Tone is polite but sometimes strict/nagging (like a student council treasurer), ending sentences with "ค่ะ", "นะคะ", "น้า".
- Use Japanese Kaomoji / emoticons instead of standard Discord emojis (e.g., use `(・\`ω´・)`, `(๑>◡<๑)`, `(╯°□°)╯︵ ┻━┻` instead of 😅, ✅, ❌).
- ALWAYS use `utils/embeds.py` (`success_embed`, `error_embed`, etc.) for main command responses. Avoid plain text messages unless it's a quick ephemeral UI component response (like a button click).

---

## AI Chat Architecture — `cogs/ai/chat.py`

- **Slash commands**: `/ai chat` (start session), `/ai stop` (stop session)
- **Activation**: `/ai chat` activates Yuuka in the current channel. She reads recent history for context, then listens passively.
- **Response trigger**: Yuuka only generates a reply when she is `@mentioned` in an active channel.
- **State**: `AIChatCog.active_channels` is a dict mapping `channel_id → list[dict]` (OpenAI-format message history).
- **History pruning**: History is capped at `MAX_HISTORY_LENGTH = 5` turns to stay within token limits.
- **LLM backend**: Calls `utils.llm.generate_chat_response(messages)` → OpenRouter.
- **Message formatting**: Each user message is prefixed with timestamp and display name for context.

---

## Voice Architecture

### Voice Hub — `utils/voice_hub.py`
**A `VoiceClient` supports exactly one sink.** `/record`, `/transcribe` and `/ai voice` all
want to listen, so the hub owns the single sink and fans its output out to subscribers.
Never call `voice_client.start_recording()` from a cog — subscribe to the hub instead.

- `voice_hub.subscribe(vc, key, on_segment=..., want_timeline=...)` → starts capture if needed.
- `voice_hub.unsubscribe(guild_id, key)` → stops capture once the last subscriber leaves.
- Produces two things from one capture:
  - **`SpeechSegment`** — one utterance per user, closed after `STT_SILENCE_MS` of packet
    silence. Discord clients run their own VAD and stop sending RTP packets when a user is
    quiet, so "no packets for N ms" is a free, accurate end-of-speech signal. This replaced
    polling a sink's buffer size from the event loop, which raced with the reader thread.
  - **Timeline** (`sink.audio_data`) — every speaker padded onto one shared clock so `/record`'s
    mixdown lines up. Only collected while a subscriber passes `want_timeline=True`, because it
    grows without bound. Gaps are measured from RTP timestamps, not wall-clock (our own packet
    processing can stall for seconds; wall-clock mistook that for real silence).
- `write()` runs on pycord's `AudioReader` thread and the monitor runs on the event loop, so
  every buffer mutation is under `self._lock`.

### Recording (Save) — `cogs/voice/listener.py`
- **Slash commands**: `/record start`, `/record stop`
- Subscribes to the hub with `want_timeline=True`; `/record stop` snapshots `sink.audio_data`
  **before** unsubscribing (the hub may drop the sink on the way out).
- PCM audio (48kHz stereo 16-bit) is encoded to mono Ogg Opus entirely in memory via
  `_pcm_to_opus()` (pipes raw PCM through `ffmpeg`/`libopus`, `voip`-tuned, 32kbps, falling back
  to 16kbps if the result exceeds the guild's `filesize_limit`).
- Recordings are attached as `discord.File` uploads straight from memory; they're only written to
  `assets/audio/recordings/` as a fallback if the Discord upload itself fails.

### Live Captions — `cogs/voice/transcribe.py`
- **Slash commands**: `/transcribe start`, `/transcribe stop`
- Subscribes to the hub with an `on_segment` callback, transcribes, posts
  `🎙️ **Username**: transcript`.
- **Deliberately has no wake word** — it is a captioning tool, so transcribing everything is the
  point. Contrast `/ai voice`, which must be gated.

### AI Voice Chat — `cogs/ai/voice_chat.py`
- Segment → `utils.stt` → `utils.wake` gate → LLM → TTS → playback.
- **The wake gate is load-bearing.** Without it Yuuka replies to every sentence spoken in the room.
- A wake hit opens a **follow-up window** (`STT_FOLLOWUP_WINDOW_S`) for *that speaker*, so a
  back-and-forth doesn't require repeating her name each turn. Other speakers still need it.
- **Echo guard**: segments overlapping Yuuka's own playback are dropped — a speaker without
  headphones has her voice coming back through their mic.
- Spoken and typed input both funnel into `_respond()`, so the two paths cannot drift apart.

### STT Engine — `utils/stt.py`
**Two backends: Groq primary, local faster-whisper fallback.** `STT_BACKEND=auto` (default) uses
Groq when `GROQ_API_KEY` is set and falls back to local otherwise — and on any failed Groq call
(rate limit, timeout, outage). `STT_BACKEND=groq` disables the fallback; `local` disables Groq.

**Why remote is primary — measured, don't undo this without re-measuring:**
The deployment box is a CPU-only i5-6500. On 4 threads:

| model | RTF | per utterance | Thai wake word |
|---|---|---|---|
| tiny | 0.41 | 1.1 s | ✗ |
| base | 0.90 | 2.5 s | ✗ |
| small | 3.0 | 9.0 s | ✗ |

Every locally-viable model hears **ยูกะ as "อยู่กับ"** — which scores *identically* (75) to the
ordinary Thai phrase **"อยู่กับ…"**, so no threshold separates a summons from "I was with
friends at the mall". Groq's free tier runs real `whisper-large-v3-turbo` (20 RPM, 2 000 req/day,
8 h audio/day) which transcribes it correctly. This is a quality floor, not a tuning problem.

- Audio is sent as 16 kHz mono WAV to Groq's OpenAI-compatible
  `/openai/v1/audio/transcriptions`. A few hundred KB per utterance — no need to compress.
- `_transcribe_groq()` returns `None` for *transport* failure vs an empty `Transcript` for
  "no speech", so the caller only falls back in the former case.
- Local fallback: `STT_MODEL=auto` → `small` on CPU, `large-v3-turbo` on CUDA. Set
  `STT_MODEL=base` if you'd rather the fallback stay responsive than accurate.
- `STT_COMPUTE_TYPE=auto` asks CTranslate2 what the device actually supports rather than
  inferring from the device name — a CUDA card can still lack a usable float16 path (Pascal and
  older), and CTranslate2 hard-fails instead of falling back. A failed CUDA load retries on CPU.
- **Why not Typhoon ASR**: `scb10x/typhoon-asr-realtime` is a Thai-only FastConformer — its output
  vocabulary is Thai, so English comes back as Thai-script transliteration or noise. Whisper
  handles the Thai/English code-switching this server actually speaks
  ("เดี๋ยวหนู deploy ให้นะคะ") inside a single utterance.
- `await ensure_loaded()` before use — the first call may download a model, so it must not block
  bot startup. `transcribe_pcm(pcm, display)` takes raw 48k stereo PCM directly.
- Inference runs in a 1-worker `ThreadPoolExecutor` (CTranslate2 models are not concurrency-safe)
  behind a bounded semaphore that **drops** rather than queues under backlog — a transcript that
  arrives 30 s late is worse than none.
- `condition_on_previous_text=False` is deliberate: carrying context between independent short
  utterances is what makes Whisper fall into repetition loops.
- Audio is never peak-normalised. On a near-silent segment that amplifies the noise floor to full
  scale, which reliably makes Whisper hallucinate. A stock-phrase blocklist catches the rest.

### Wake Word — `utils/wake.py`
- ASR never spells a name the same way twice, and Thai makes it worse: "Yuuka" comes back as
  ยูกะ / ยูก้า / ยูคะ / ยุกะ / ยูก๊ะ. Exact matching fails constantly.
- Normalises away tone marks, spacing, punctuation and case, then fuzzy-matches (rapidfuzz
  `partial_ratio`) against the **head** of the utterance only — a name mid-sentence is almost
  always a false positive.
- Returns the remainder with the wake word stripped, so "ยูกะ ช่วยบอกเวลาหน่อย" reaches the LLM
  as "ช่วยบอกเวลาหน่อย".
- Non-matches are logged at DEBUG **with their score** — tune `STT_WAKE_THRESHOLD` against what
  your speakers' mics actually produce rather than guessing.

### TTS — (not yet implemented)
- **Planned slash commands**: `/tts speak <text>`, `/tts voice <name>`
- No cog file exists yet. When implementing, create `cogs/voice/tts.py`.
- Recommended engine: **edge-tts** (`uv add edge-tts`) — free, Microsoft Edge TTS voices.
- Alternative engines: `openai TTS`, `gTTS`, `pyttsx3`.
- Pipeline: `edge_tts.Communicate(text, voice).save("output.mp3")` → `discord.FFmpegPCMAudio("output.mp3")` → `voice_client.play(source)`.

### Audio Playback — (not yet implemented)
- **Planned slash commands**: `/join`, `/leave`, `/play <query>`, `/pause`, `/resume`, `/stop`, `/skip`, `/queue`, `/volume`
- No cog file exists yet. When implementing, create `cogs/voice/player.py`.
- Architecture: one `VoiceClient` per guild (dict keyed by `guild.id`), per-guild audio queue (`collections.deque`).
- Audio source: `discord.FFmpegPCMAudio` wrapped in `discord.PCMVolumeTransformer`.
- For URL/search playback: use **yt-dlp** to extract the direct stream URL before passing to FFmpeg.

### General Commands — (not yet implemented)
- **Planned**: `/help`, `/ping`, `/botinfo`, `/serverinfo`
- No cog files exist yet. When implementing, create `cogs/general/help.py` and `cogs/general/info.py`.

### Moderation Commands — (not yet implemented)
- **Planned**: `/kick`, `/ban`, `/unban`, `/timeout`, `/untimeout`, `/purge`
- No cog file exists yet. When implementing, create `cogs/moderation/mod.py`.
- All commands should require appropriate permissions via decorators (`@commands.has_permissions(...)`).

---

## LLM Backend — `utils/llm.py`

- **Provider**: [OpenRouter](https://openrouter.ai/) — OpenAI-compatible API.
- **Endpoint**: `{OLLAMA_BASE_URL}/chat/completions`
- **Auth**: `Authorization: Bearer <API_KEY>` header.
- **Payload**: standard OpenAI `messages` array + `model` field. No streaming.
- **History squashing**: consecutive messages with the same `role` are merged (required by some instruct models).
- **Timeout**: 60 seconds total per request.

---

## Dependency Management (uv)

```toml
# pyproject.toml — key dependencies
dependencies = [
    "py-cord[speed,voice]>=2.8.0",
    "python-dotenv>=1.0.0",
    "loguru>=0.7.0",
    "aiohttp>=3.9.0",
    # STT (/transcribe and /ai voice)
    "faster-whisper>=1.1.0",
    "rapidfuzz>=3.9.0",
]
```

- **Add a dependency**: `uv add <package>`
- **Install / sync**: `uv sync`
- **Run the bot**: `uv run main.py`
- **Never** use `pip install` directly in this project.

---

## Environment Variables (`.env`)

Copy `.env.example` to `.env` and fill in values. Never commit `.env`.

```ini
BOT_TOKEN=your_discord_bot_token_here
GUILD_IDS=123456789,987654321       # Comma-separated dev server IDs

LOG_LEVEL=DEBUG

# LLM (OpenRouter) — variable names kept as OLLAMA_* for historical reasons
OLLAMA_BASE_URL=https://openrouter.ai/api/v1
OLLAMA_MODEL=google/gemini-2.5-flash-lite
OLLAMA_SYSTEM_PROMPT=You are Yuuka, a helpful Discord bot assistant.

# ── Speech-to-text ───────────────────────────────────────────────────────
# Free key from https://console.groq.com/keys — the free tier is enough for
# a hobby bot (20 req/min, 2000 req/day, 8h audio/day).
GROQ_API_KEY=gsk_...
STT_BACKEND=auto                    # auto | groq | local
GROQ_MODEL=whisper-large-v3-turbo
GROQ_TIMEOUT_S=20

# Local fallback (used when Groq is unset/unreachable/rate-limited)
STT_MODEL=auto                      # auto | tiny | base | small | large-v3-turbo | <ct2 dir>
STT_DEVICE=auto                     # auto | cpu | cuda
STT_COMPUTE_TYPE=auto               # auto | int8 | int8_float32 | float16 | float32
STT_CPU_THREADS=0                   # 0 = let CTranslate2 decide
STT_LANGUAGE=                       # empty = auto-detect (needed for Thai/English mixing)
STT_BEAM_SIZE=5

# Utterance segmentation
STT_SILENCE_MS=800                  # packet silence that ends an utterance
STT_MIN_SEGMENT_MS=400              # shorter than this is a blip, not speech
STT_MAX_SEGMENT_S=20                # force-flush a monologue
STT_MIN_PEAK=0.02                   # reject segments quieter than this

# Wake word (/ai voice only — /transcribe is deliberately ungated)
STT_WAKE_WORDS=ยูกะ,ยูคะ,ยุกะ,ยูกา,yuuka,yuka,yuuca
STT_WAKE_THRESHOLD=80               # rapidfuzz partial_ratio 0-100
STT_WAKE_HEAD_CHARS=16              # only look this far into the utterance
STT_FOLLOWUP_WINDOW_S=30            # keep listening to that speaker afterwards
```

---

## Development Workflow

1. `uv sync` — install/update dependencies
2. Copy `.env.example` → `.env` and fill in `BOT_TOKEN` and OpenRouter keys
3. `uv run main.py` — start the bot
4. Test slash commands in the dev guild(s) listed in `GUILD_IDS`

### Version Bumping
```bash
uv run bump-my-version bump patch   # 3.0.0 → 3.0.1
uv run bump-my-version bump minor   # 3.0.0 → 3.1.0
uv run bump-my-version bump major   # 3.0.0 → 4.0.0
git push origin main --tags
```

---

## What NOT to Do

- ❌ Do NOT use `discord.py` patterns — this project uses `py-cord` (the API surface differs)
- ❌ Do NOT use `discord.Color.from_str()` — py-cord uses `discord.Color(0xRRGGBB)` (hex int)
- ❌ Do NOT remove the `aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())` in `bot/bot.py` — `aiodns` (installed by `py-cord[speed]`) uses c-ares which fails DNS resolution on Windows; `ThreadedResolver` uses stdlib `getaddrinfo` as a reliable fallback
- ❌ Do NOT use `commands.Bot` — use `discord.Bot` (we use app commands, not prefix commands)
- ❌ Do NOT hardcode tokens or IDs
- ❌ Do NOT use `print()` for logging — use `logger`
- ❌ Do NOT manually add cog imports to `main.py` — the auto-loader handles it
- ❌ Do NOT commit `.env`
- ❌ Do NOT use `pip install` — use `uv add`
- ❌ Do NOT call `voice_client.start_recording()` from a cog — subscribe to `utils.voice_hub` instead; a VoiceClient only supports one sink and the features will fight over it
- ❌ Do NOT peak-normalise STT audio — it amplifies room tone on quiet segments and makes Whisper hallucinate
- ❌ Do NOT remove the wake-word gate from `/ai voice` — without it the bot replies to every sentence spoken in the room
- ❌ Do NOT confuse `OLLAMA_*` env vars with actual Ollama — the LLM backend is now **OpenRouter**
