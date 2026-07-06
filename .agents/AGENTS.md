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
2. **Voice speaking** — join voice channels and play audio (music, TTS, sound effects)
3. **Voice listening** — receive and process audio from users via pycord's sink API
4. **AI integration** — future AI features will hook into voice listening and command outputs

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
│   ├── voice/                # Voice feature group
│   │   ├── __init__.py
│   │   ├── player.py         # Audio playback — join/leave/play/pause/stop/queue
│   │   ├── listener.py       # Voice receive — pycord sinks, AI audio pipeline hook
│   │   └── tts.py            # Text-to-speech via voice channel
│   ├── general/              # General commands
│   │   ├── __init__.py
│   │   ├── help.py           # /help — custom help command
│   │   └── info.py           # /ping, /botinfo, /serverinfo
│   └── moderation/           # Moderation commands
│       ├── __init__.py
│       └── mod.py            # /kick, /ban, /timeout, etc.
│
├── utils/                    # Shared utilities (no Discord state — pure helpers)
│   ├── __init__.py
│   ├── checks.py             # Custom @commands.check() decorators
│   ├── embeds.py             # Embed builder factories
│   └── errors.py             # Global on_application_command_error handler
│
└── assets/
    └── audio/                # Local audio files (sfx, cached TTS, etc.)
```

---

## Key Conventions & Patterns

### 1. Bot Subclass (`bot/bot.py`)
- The bot is an instance of `YuukaBot(discord.Bot)`.
- Use `discord.Bot` (NOT `commands.Bot`) since we use **slash/application commands only**.
- Required intents: `guilds`, `voice_states`, `message_content` (for message context menus).
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
- During **development**, pass `guild_ids=config.GUILD_IDS` to sync commands instantly to test servers.
- In **production**, omit `guild_ids` for global command sync.

### 4. Config (`bot/config.py`)
- All secrets and settings are loaded from `.env` via `python-dotenv`.
- Access config via the singleton `config` object imported from `bot.config`.
- **Never** hardcode tokens, IDs, or secrets anywhere else.
- Key config values:
  - `BOT_TOKEN` — Discord bot token
  - `GUILD_IDS` — comma-separated guild IDs for dev slash command sync
  - `LOG_LEVEL` — logging verbosity (`DEBUG`, `INFO`, `WARNING`)

### 5. Logging (`bot/logger.py`)
- Uses **loguru** (`from loguru import logger`).
- All modules import the shared logger: `from bot.logger import logger`
- Do NOT use `print()` for debugging — use `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`.
- Log format includes timestamps, level, and the calling module.

### 6. Embeds (`utils/embeds.py`)
- All user-facing responses should use Discord embeds, not plain text.
- Use factory functions from `utils.embeds` to build consistent-looking embeds.
- Standard color palette: success=green, error=red, info=blurple, warning=yellow.

### 7. Error Handling (`utils/errors.py`)
- A global `on_application_command_error` listener handles all unhandled exceptions.
- Individual cogs should `try/except` their own logic and raise `discord.ApplicationCommandError` subclasses for user-facing errors.
- Never let raw tracebacks reach the user.

---

## Voice Architecture

### Speaking (Playback) — `cogs/voice/player.py`
- Manages one `VoiceClient` per guild, stored in a dict keyed by `guild.id`.
- Audio queue is a `collections.deque` per guild.
- Uses `discord.FFmpegPCMAudio` wrapped in `discord.PCMVolumeTransformer`.
- For streaming URLs (YouTube, etc.), use **yt-dlp** to extract the stream URL before passing to FFmpeg.
- Key slash commands: `/join`, `/leave`, `/play <query>`, `/pause`, `/resume`, `/stop`, `/skip`, `/queue`

### Listening (Receive) — `cogs/voice/listener.py`
- Uses pycord's **Sink API** (`discord.sinks`).
- `bot.voice_clients` holds active voice connections.
- Recording is started with `voice_client.start_recording(sink, callback, *args)`.
- The `callback` is called when recording stops — audio data is available as `sink.audio_data` (dict of `user_id → AudioData`).
- **AI hook**: The callback should forward raw PCM audio to an AI pipeline (STT, hotword detection, etc.). This pipeline is NOT implemented yet — leave a clearly marked `# TODO: AI PIPELINE HOOK` comment.
- Key slash commands: `/listen start`, `/listen stop`

### TTS — `cogs/voice/tts.py`
- Converts text to audio and plays it through the voice channel.
- Implementation is a stub — the actual TTS engine (e.g., edge-tts, Google TTS, OpenAI TTS) will be chosen later.
- Leave a clearly marked `# TODO: TTS ENGINE` comment.

---

## Dependency Management (uv)

```toml
# pyproject.toml dependencies
dependencies = [
    "py-cord[speed,voice]>=2.8.0",
    "python-dotenv>=1.0.0",
    "loguru>=0.7.0",
    "yt-dlp>=2024.0.0",
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
GUILD_IDS=123456789,987654321   # Comma-separated dev server IDs
LOG_LEVEL=DEBUG
```

---

## Development Workflow

1. `uv sync` — install/update dependencies
2. Copy `.env.example` → `.env` and fill in `BOT_TOKEN`
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
