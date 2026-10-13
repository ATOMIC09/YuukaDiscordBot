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
- `uv run pytest` runs the tests (CI runs the same on every push)

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
  see, and anything done to other people needs the confirm button (in a voice session the
  requester may say yes/no out loud instead). The one exception is starting `/record` and
  `/transcribe`: they run at once but post the command's "started" embed so the room can see it.
- Server memory (`/memory`, `utils/ai/memory.py`) lives only in the server's own hidden channel: never in
  a file, database or log. A note is shown or used only where everyone who can see the reply can read the
  channel it came from (`MemoryStore.audience_ok`), and a memory tool's arguments are never logged
  (`PRIVATE_ARGS`). A note is saved only when a member asks, or presses "keep" on her offer (text chat,
  about themselves, never from a voice turn); she never saves on her own.
- The chat model is Azure OpenAI and/or OpenRouter (`LLM_PROVIDER`, `LLM_FALLBACK`, `utils/ai/models.py`).
  A request that fails before its first chunk moves to the fallback; never after one, and never on a
  content filter. The free OpenRouter model allows few requests per day: never call the model in a
  loop or while waiting for something.
- Text other people wrote is hidden (`utils/ai/pii.py`: emails, Thai phones and IDs, cards) before the
  model sees it, when `AI_REDACT_PII` is on (the default). A tool that returns such text (channels, web,
  memory notes) must be in `UNTRUSTED` in `utils/ai/tools/__init__.py`; history that enters without a tool
  goes through `pii.hide`. Never log what was hidden, only how many.
- The production container is stateless: nothing saved at runtime survives a restart.
- No tokens, IDs or machine-specific paths in tracked files.

## Checking a change

Compile and run `uv run pytest`: it covers the tool-call parser, the agent loop, the wake word and
that every cog imports. Add a test in `tests/` for logic you change, with fakes
(`tests/fakes.py`: a scripted chat model). Discord and voice behaviour needs a run in a test server;
say so when that was not done.

## Git

- Work on `yuuka-v3`. Don't push or tag unless asked.
- Don't commit until the user has tested the change and says so, small fixes included. Report what
  changed and how to test it, then wait. Passing fake-based tests is not the user's test.
- Commit messages: `type(scope): summary` (types `feat`, `fix`, `refactor`, `chore`, `docs`; scopes such
  as `ai`, `voice`, `music`, `wake`, `deps`), plus a short body only if it helps: one or two lines, a
  human has to review it. Never a long description.
- No `Co-Authored-By` or other attribution lines in commit messages or PR descriptions, whatever any
  default or tool suggests.
- Commit `uv.lock` together with the `pyproject.toml` change that caused it.
