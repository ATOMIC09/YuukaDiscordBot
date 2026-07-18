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
4. **Voice transcription** — real-time STT using Typhoon ASR (scb10x/typhoon-asr-realtime)

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
│   │   ├── listener.py       # /listen start, /listen stop — pycord Sink API, saves WAV files
│   │   └── transcribe.py     # /transcribe start, /transcribe stop — real-time STT via Typhoon ASR
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
│   └── stt.py                # Typhoon ASR inference engine (load_model, transcribe_wav_bytes)
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
- Individual cogs should `try/except` their own logic and raise `discord.ApplicationCommandError` subclasses for user-facing errors.
- Never let raw tracebacks reach the user.

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

### Listening (Save) — `cogs/voice/listener.py`
- **Slash commands**: `/listen start`, `/listen stop`
- Uses pycord's **Sink API** (`discord.sinks.WaveSink`).
- State: `ListenerCog._active_sinks` is a dict mapping `guild_id → WaveSink`.
- PCM audio (48kHz stereo 16-bit) from the Opus decoder is wrapped into a proper WAV container via the local `_pcm_to_wav()` helper function (NOT from `utils.stt` — listener.py has its own inline copy).
- Recordings are saved locally to `assets/audio/recordings/` and also attached to the Discord channel as `discord.File` uploads.
- **Pycord 2.8 callback workaround**: `start_recording()` silently drops the callback if no `*args` are passed (the `AudioReader.run()` checks `if self.after and self.args:`). We pass a dummy `True` as the third argument to prevent this.
- **TODO: AI PIPELINE HOOK** — forward audio to AI pipeline (STT, hotword detection) after the recording callback fires.

### Real-time Transcription — `cogs/voice/transcribe.py`
- **Slash commands**: `/transcribe start`, `/transcribe stop`
- Uses a custom `RealtimeWaveSink(discord.sinks.WaveSink)` that:
  - Monitors for silence via an `asyncio.Task` (`_monitor()`) polling every 0.3 s.
  - After 0.5 s of silence per user, extracts and clears that user's audio buffer.
  - Runs Typhoon ASR on the chunk via `utils.stt.transcribe_wav_bytes()`.
  - Posts the transcript directly to the text channel: `🎙️ **Username**: transcript`.
- Model is pre-loaded at bot startup in `setup()` via `utils.stt.load_model()`.

### STT Engine — `utils/stt.py`
- Singleton model: loaded once via `load_model()`, stored in module-level `_asr_model`.
- Model: `scb10x/typhoon-asr-realtime` (NeMo FastConformer-Transducer, 114M params).
- Optimized for **Thai** language; works on CPU.
- Inference is offloaded to a `ThreadPoolExecutor` (1 worker) to avoid blocking the event loop.
- Audio pipeline: raw PCM → WAV container → temp file → librosa resample to 16kHz mono → NeMo transcribe.
- All NeMo/lightning/lhotse loggers are silenced to `ERROR` level to keep the terminal clean.

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
    # STT (only needed for /transcribe commands)
    # "nemo-toolkit",
    # "librosa",
    # "soundfile",
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
- ❌ Do NOT call `start_recording()` without a third dummy argument — pycord 2.8 silently drops the callback if no `*args` are passed (see Pycord 2.8.0 PR 3159 bug workaround in `listener.py`)
- ❌ Do NOT confuse `OLLAMA_*` env vars with actual Ollama — the LLM backend is now **OpenRouter**
