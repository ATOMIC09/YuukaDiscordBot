# CLAUDE.md

Yuuka is a Thai-speaking Discord bot (py-cord, Python 3.12, uv). This file is the short version;
the full architecture and the reasons behind it are in `.agents/AGENTS.md`, imported below. Release
steps are in `.agents/DEVELOPMENT.md`. When a rule changes, update both files.

@.agents/AGENTS.md

## Commands

- `uv sync` installs dependencies (GPU box: `uv sync --extra cuda`)
- `uv run main.py` runs the bot; it needs a `.env` (copy `.env.example`)
- `uv add <package>` adds a dependency (never `pip install`)
- `uv run python -m compileall -q bot cogs utils` checks syntax

## Rules that break things when ignored

- py-cord, not discord.py: `discord.Bot` (not `commands.Bot`), colors as `discord.Color(0xRRGGBB)`.
- Cogs under `cogs/` load automatically; each file needs `setup(bot)`. Never register them in `main.py`.
- Settings only through `from bot.config import config`. A new setting needs a `Config` field, parsing
  in `from_env()`, and a line in `.env.example`.
- Log with `from bot.logger import logger`, never `print`.
- Refuse bad input by raising `UserError` / `UserWarning` from `utils.errors`; the global handler shows it.
- User-facing text is in Yuuka's persona: Thai, calls the user "เซนเซย์" and herself "หนู", kaomoji
  instead of emoji, embeds from `utils.embeds`.
- Voice receive goes through `utils.voice_hub`; never call `start_recording()` in a cog.
- One `VoiceClient` per guild is shared by the music player and `/ai voice` speech.
- AI agent: LangChain core only (never `langchain` or `langgraph`). Tools live in `utils/ai/tools/` and
  are offered by `tools_for`. Everything a tool finds or lists is filtered by what the requester can
  see, and anything done to other people needs the confirm button.
- The free OpenRouter model allows few requests per day: never call the model in a loop or while
  waiting for something.
- The production container is stateless: nothing saved at runtime survives a restart.
- No tokens, IDs or machine-specific paths in tracked files.

## Checking a change

There is no test suite. Compile, import every cog, and test logic with a throwaway script that uses
fakes (keep it out of the repo). Discord and voice behaviour needs a run in a test server; say so when
that was not done.

## Git

- Work on `yuuka-v3`. Don't push or tag unless asked.
- Commit messages: `type(scope): summary` (types `feat`, `fix`, `refactor`, `chore`, `docs`; scopes such
  as `ai`, `voice`, `music`, `wake`, `deps`), plus a short body only if it helps.
- Commit `uv.lock` together with the `pyproject.toml` change that caused it.
