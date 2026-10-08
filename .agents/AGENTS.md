# Yuuka Discord Bot — Agent Knowledge Base

This document is the canonical reference for all agents working on this project.
Read this file before making any changes to understand the architecture, conventions, and patterns used.

---

## Project Overview

**Yuuka** is a Thai-speaking Discord bot (persona: Yuuka from Blue Archive) built with:
- **[py-cord](https://docs.pycord.dev/)** (`py-cord[speed,voice]`, installed from a PR ref in `[tool.uv.sources]`) — Discord API wrapper (NOT `discord.py`)
- **[uv](https://astral.sh/uv)** — Python package & virtual environment manager
- **Python 3.12–3.13**

Main features:
1. **AI chat** (`/ai chat`, `@mention`) — an agent on OpenRouter (LangChain core) that can search the web, read channels, control music, look up members and set reminders
2. **AI voice chat** (`/ai voice`) — wake-word-gated spoken conversation (STT → agent → TTS)
3. **Music player** (`/music …`) — yt-dlp streaming with queue, loop, seek and crossfade
4. **Voice tools** — recording, live captions, attendance, kick, countdown disconnect
5. **Image tools** — `/image …` and right-click message commands

---

## Project Structure

```
YuukaDiscordBot/
├── main.py                   # Entry point: builds YuukaBot, loads cogs, runs
├── pyproject.toml, uv.lock   # uv manifest and lock (commit them together)
├── .env.example              # Every env var bot/config.py reads — copy to .env
├── Dockerfile                # Production image (ffmpeg + uv sync --frozen --no-dev)
├── .github/workflows/        # docker-build.yml: publishes the image to ghcr.io on a v*.*.* tag
│
├── bot/
│   ├── bot.py                # YuukaBot(discord.Bot) — intents, cog loader
│   ├── config.py             # .env → frozen Config dataclass (singleton `config`)
│   └── logger.py             # Loguru setup — import `logger` from here
│
├── cogs/                     # Auto-loaded: every *.py except __init__.py
│   ├── ai/
│   │   ├── __init__.py       # The shared /ai SlashCommandGroup
│   │   ├── chat.py           # /ai chat, /ai voice, /ai stop; @mention replies; owns the reminder scheduler
│   │   └── voice_chat.py     # Voice-chat logic (no commands of its own; chat.py calls it)
│   ├── voice/
│   │   ├── player.py         # /music … — the music player (PlayerCog)
│   │   ├── listener.py       # /record start|stop
│   │   ├── transcribe.py     # /transcribe start|stop — live captions (no wake word)
│   │   ├── attendance.py     # /attendance (with CSV), /absent
│   │   ├── kick.py           # /kick — disconnect a member from voice
│   │   └── countdis.py       # /countdis — countdown, then disconnect everyone
│   ├── general/
│   │   ├── help.py           # /help
│   │   ├── info.py           # /status, /user, /server
│   │   ├── image.py          # /image pet|resize|scale|qr + Deepfry/Grayscale/Wide/Image Info message commands
│   │   ├── imgaudio.py       # /imgaudio — video from the channel's latest image and audio
│   │   ├── feedback.py       # /feedback → FEEDBACK_CHANNEL_ID
│   │   ├── logging.py        # Logs every command to LOG_CHANNEL_ID, including ones Yuuka runs (log_ai_command)
│   │   ├── admin.py          # /reload (owner only)
│   │   └── send.py           # /send (owner only)
│   └── moderation/           # Empty placeholder package
│
├── utils/
│   ├── ai/                   # The agent: agent.py, tool_calling.py, models.py, context.py, confirm.py, scheduler.py, tools/
│   ├── attendance.py         # /attendance and /absent report builders (shared by the cog and the agent tools)
│   ├── ai_actions.py         # Runs /music commands for the agent, posts their embeds and logs them (log_command)
│   ├── web_search.py         # Tavily search with an in-memory TTL cache
│   ├── embeds.py             # Embed factories (success/error/info/warning)
│   ├── errors.py             # UserError / UserWarning + global command error handler
│   ├── checks.py             # Custom command checks
│   ├── voice_hub.py          # Single owner of voice receive; emits SpeechSegments
│   ├── stt.py                # Groq / faster-whisper transcription
│   ├── wake.py               # Fuzzy text wake-word gate
│   ├── wake_acoustic.py      # Acoustic wake-word pre-filter (model in models/)
│   ├── tts.py                # Edge TTS → temp MP3
│   ├── chime.py              # Wake / "done" earcons for /ai voice (synthesised in memory)
│   ├── audio.py              # PCM helpers
│   ├── image.py              # Image effects for /image
│   └── video.py              # ffmpeg helpers for /imgaudio
│
├── models/wake_word/         # Trained wake-word model used by wake_acoustic.py
├── wakeword_training/        # Offline training/eval scripts for that model — not loaded by the bot
└── assets/audio/recordings/  # Fallback location for /record output (created at runtime)
```

---

## Key Conventions & Patterns

### 1. Bot Subclass (`bot/bot.py`)
- The bot is an instance of `YuukaBot(discord.Bot)`.
- Use `discord.Bot` (NOT `commands.Bot`) since we use **slash/application commands only**.
- Intents: the defaults plus `members`, `presences`, `voice_states` and `message_content`. `members` is load-bearing: the agent resolves members by name, and with it `message.author` is the live cached `Member`.
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
- Commands register **globally**. `GUILD_IDS` is parsed into `config.guild_ids`, but no cog passes it yet.

### 4. Config (`bot/config.py`)
- All settings come from `.env` via `python-dotenv` and are exposed as the frozen singleton `config`
  (`from bot.config import config`). Never read `os.environ` elsewhere, and never hardcode tokens or IDs.
- **`.env.example` lists every variable with its default.** Adding a setting means three edits: a field
  in `Config`, parsing in `from_env()`, and a line in `.env.example`.
- Required: `BOT_TOKEN`, `OPENROUTER_API_KEY`, `OPENROUTER_SYSTEM_PROMPT` — startup fails without them.
  Optional keys switch a feature off when empty (no `TAVILY_API_KEY` = no web search, no
  `GROQ_API_KEY` = local STT only).
- In `.env`, keep comments on their own line when a value is empty: python-dotenv reads
  `KEY=   # note` as the value `# note`.

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
- **Activation**: `/ai chat` activates Yuuka in the current channel. She reads recent history for context (her own embeds come in as one `[result] …` line each; the static session-start embeds are just "เริ่มการสนทนา"), then listens passively.
- **Response trigger**: Yuuka only generates a reply when she is `@mentioned` in an active channel.
- **State**: `AIChatCog.active_channels` is a dict mapping `channel_id → list[dict]` (OpenAI-format message history).
- **History pruning**: capped at `MAX_HISTORY_LENGTH` messages (default 50); the system prompt is always kept.
- **LLM backend**: Calls `utils.ai.run_agent(history, ctx)` → OpenRouter (see "LLM Backend" below).
- **Reminders**: `AIChatCog.scheduler` (`utils/ai/scheduler.py`) holds in-memory reminders and voice-join watches; its `on_voice_state_update` listener fires the watches.
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
- **No standing follow-up window** (the exceptions below: a pending confirmation, the answer to a
  question she just asked, and the listening window after a bare wake word) — every request needs
  the wake word. (An earlier version kept a speaker "awake" for a few seconds after a hit; removed
  because it confused people about when they still needed to say her name.)
- **Chime, then listen (Assistant style)**: the moment her name is recognised she plays a short
  chime (`utils/chime.py`: synthesised in memory, `discord.PCMAudio`, so nothing sits in front of
  it — no TTS, no ffmpeg), and a bare name opens a listening window (`_start_listening`,
  `STT_LISTEN_WINDOW_S`) for that speaker's next utterance, which goes straight to the LLM with no
  acoustic/wake re-check. The window is `session.awaiting_answer` (the same one-use entry as the
  answer window below); `session.listening` holds a task that plays the closing chime if the window
  ran out unused. A cough (empty transcript) does not use it up, and a sentence that started before
  the deadline still counts. This also covers "Yuuka, *(pause)*, what time is it": `voice_hub` cuts
  a segment on ~800ms of packet silence, so the name and the question arrive as two segments.
- **The acoustic gate scores every 80 ms hop, short segments included** (`utils/wake_acoustic.py`): a
  full window of silence goes in front of the segment, so a window ends at every hop of it. A segment
  of 2 s or less (every bare name) used to get one window ending at its last sample; the audio Discord
  keeps sending after the speaker stops (longer with music) moved the word off that spot and the score
  fell to about 0. Each segment logs `[Wake Acoustic] best … (end window alone …)`: the second number
  is what the old scoring gave, so a best far above it is a summon that used to be dropped. Scanning lets
  more segments reach STT, and v3 turned out to fire on "silence, then any short sound" (quiet room noise
  in front of the name drops it to 0%, music and voices alone pass about 60% at 0.4), so the default is
  v2 at 0.6. `STT_WAKE_ACOUSTIC_COMPARE_PATH` (dev only, empty in production) scores a second model on
  the same windows and logs it beside the first; it never decides.
- **The signal waits for the transcript**: a segment is only known at its end (`STT_SILENCE_MS`), and
  the acoustic score is not proof of her name (v3 scored 0.4-0.6 at best on a clear Thai voice, 0.0-0.1
  with noise, and varied a lot between speakers, measured with the single-window scoring above; it also
  fires on ordinary talk). So the chime and the
  listening window only come after `wake.detect` matches the transcript. The score only decides whether
  a segment is worth transcribing. A segment from the same speaker that arrives while the name is
  still in STT waits for the verdict (`session.verifying`, at most `_VERDICT_WAIT_S`) instead of being
  gated on its own, so "Yuuka" + an immediate request still works. An earlier version chimed on the
  gate and took it back; people heard a chime for chatter, and "confident score" shortcuts built on the
  same assumption (a short clip "must be her name") swallowed real commands. Both were removed;
  `STT_WAKE_ACOUSTIC_CONFIDENT_SCORE` and `STT_WAKE_RELAXED_THRESHOLD` stay in `Config` and
  `.env.example`, marked unused, for a future model that scores reliably.
- **Her name while listening** (spamming it because nothing seemed to happen) is not the request:
  a transcript that is just her name restarts the window with a fresh signal (`_relisten`) and never
  reaches the LLM; a name followed by words is cut out of the request.
- **The chime itself**: starts with 150 ms of silence, because clients clip the opening of a short
  sound that arrives with the speaking signal. The first sound on a fresh connection is clipped
  even more (a chime was inaudible until her first spoken reply), so `_open_session` plays 400 ms of
  silence to open the stream (`chime.warm_up`), and a client that has sent no audio yet (`_WARM`)
  gets a 600 ms lead-in once. Every call logs `[Chime] … playing` or why it was skipped. It never interrupts her own speech (one `VoiceClient`). Over a playing track it is mixed into the
  track's mixer instead (see "Speaking over music"); only a paused track skips it, and then a short
  text notice stands in, posted at the same moment, deleted when the window closes.
- **The chime means "I am listening for you"**, so it also sounds whenever she waits for an answer:
  after a reply that asks a question (the answer window, `STT_ANSWER_WINDOW_S`, same closing chime
  if unused) and when a `voice_kick` / `voice_disconnect_timer` confirmation is posted (`expect_answer`).
  Both run after her line has finished, so the voice client is free.
- **Several speakers**: one reply is generated per guild at a time (`session.busy`). A request that
  arrives meanwhile, from another person or the same one, waits in `session.pending` (at most
  `_MAX_PENDING`) and is answered in turn by the loop in `_respond`; it enters the history only when
  its turn starts, so history keeps the order she answered in. A person whose request is already being
  answered or queued (`_already_asked`) who says the bare name again, or the same request again, is
  ignored with no chime and no listening window: it is someone who thinks she did not hear. With more
  than one human in the voice channel `_sync_speaker_note` adds `_MULTI_SPEAKER_NOTE` to the system
  prompt so replies start with the speaker's name; it is removed again when they are alone.
- **Timing logs**: each spoken turn logs `[Timing] <speaker>: <stage> +N.NNs` (acoustic gate, transcript,
  chime, asking the model, model finished, speech synthesized, first sound or "answer posted as
  text"), counted from when the hub closed the segment (`STT_SILENCE_MS` after the speaker stopped).
  The `_Timing` object rides on each queued clip because the audio worker plays it after `_respond`
  has returned. Read these before guessing why a reply felt slow.
- **Bots are never speakers**: `_on_segment` drops segments from other bot accounts before any STT.
  A second Yuuka in the room (a test instance) hears the first one's chime as a wake word and
  answers with its own, and the two chime at each other every ~3 s, each round costing STT requests
  until Groq's rate limit hit (seen in production).
- **Echo guard**: segments overlapping Yuuka's own playback are dropped — a speaker without
  headphones has her voice coming back through their mic.
- Spoken and typed input both funnel into `_respond()`, so the two paths cannot drift apart.
- **Speaking around tools**: text the model writes right before a tool call is dropped
  (`tool_calling.py`): gpt-oss fills that slot with its reasoning. So the room is quiet while a
  tool runs, and a tool that ends the turn speaks its own line instead: `spoken_fallback` for
  music, `before_action(text)` for reminders and confirmations. Anything already written is still
  spoken on each `status` event (`spoken_upto`). `_speak` strips links for TTS only; text
  fallbacks keep them. One `VoiceClient` is shared with music; she speaks over a track
  (below) and posts text instead (`_post_unspoken`) only when she cannot be heard at all.
- **Speaking over music**: `vc.play()` raises on a busy client, so while a track plays her chime and
  voice go through the track's own mixer: `SeamlessCrossfadeSource.add_overlay(pcm, on_done)` mixes
  them into the music frames on the voice send thread and ducks the music (`DUCK_GAIN`, ramped over
  `DUCK_ATTACK_FRAMES` / `DUCK_RELEASE_FRAMES`). `utils.audio.music_mixer(vc)` finds the mixer, and is
  None for a paused track (a paused mixer is not read, so a sound added to it would never play) or
  when her own clip owns the client. `_audio_worker` decodes the MP3 to PCM (`decode_to_pcm`) and waits
  for `on_done`, which is also called on `cleanup()` so a stopped track cannot strand it. While she
  speaks over music `speaking_until` is finite: `stop_session` treats an infinite one as her own clip
  and calls `vc.stop()`, which would kill the track. Her voice is raised by `SPEECH_OVER_MUSIC_GAIN`
  (`boost_pcm`: tanh soft limit, so a hot track can be outshouted without clipping; the chime is
  not boosted). Without a track nothing changes: she `play()`s directly.
- **Answer to her question**: when a reply ends by asking something (`_asks_user`: a `?`, or Thai
  `คะ` that is not `นะคะ`, or a question word at the end), that speaker's next utterance within
  `STT_ANSWER_WINDOW_S` goes straight to the LLM with no wake word. The window opens when she
  finishes speaking, belongs to that speaker alone and is used up by one utterance, so it is not
  the follow-up window removed earlier; a reply that asks again opens a new one.
- **Spoken confirmation**: after `voice_kick` / `voice_disconnect_timer` propose an action, the
  requester can say "ยืนยัน" or "ยกเลิก" instead of pressing the button. This is the one input heard
  without the wake word: only from the requester, only while their `ConfirmActionView` is open (60 s),
  and only a short utterance (`spoken_decision` in `utils/ai/confirm.py`; a "no" word beats a "yes"
  word). Anything else from them goes through the normal wake gate. It costs one STT request and no
  LLM request; the outcome is spoken back via `announce`.
- **`announce(guild_id, text)`**: speaks results that arrive after a turn ends (confirmed actions,
  fired reminders); silent if music or her own speech holds the voice client.

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
- **Language shortlist** (`STT_LANGUAGE`): Groq takes one language, so an answer outside the list is re-requested once
  with the first listed language forced, except a Thai-sounding one (vi, id, ms, lo, km, my) when `th` is listed:
  a short Thai phrase is often misdetected as those, and forcing English on it gave romanised noise.
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
  `partial_ratio`) against the **whole utterance**, but a hit only counts at the start (after at most
  `_MAX_LEAD_CHARS`, a "เฮ้ย"/"hey") or the end (before at most `_MAX_TRAIL_CHARS`, a "ครับ"/"นะคะ"):
  a name deeper in a sentence is talk about her ("ต้องพูดคำว่า ยูกะ ร้อยรอบ"), not a summons. Thai puts the vocative at the end as often as
  the front — "แล้วอีกแบบคืออะไรล่ะยูกะ" scores 29 on the first 16 chars and 100 on the whole line —
  so a head-only match misses half of real summons. It costs less precision than it looks: the
  phrase it collides with, "อยู่กับ", scores 75 either way, because it is a near-miss of the *name*
  rather than an artefact of where we searched. The default threshold of 80 sits in that gap.
  `STT_WAKE_HEAD_CHARS` can still restrict the search for a room noisy enough to need it.
- Returns the utterance with the wake word **cut out wherever it sat**, so both
  "ยูกะ ช่วยบอกเวลาหน่อย" and "ช่วยบอกเวลาหน่อยยูกะ" reach the LLM as "ช่วยบอกเวลาหน่อย". A leftover of fewer than
  3 characters is dropped (`_MIN_REMAINDER_CHARS`): the match ignores Thai marks, so a misheard
  "โยกา" is cut as "ยกา" and leaves a stray "โ", which used to be sent to the LLM as the request.
- **Japanese folds two ways.** Katakana maps onto hiragana by a fixed offset, and the 長音符 `ー`
  is spelled out as the vowel it lengthens, so ユーカ / ユウカ / ゆーか / ゆうか all normalise to
  ゆうか and one listed variant covers every spelling Whisper might choose. Without this a
  katakana line scores **0** against a hiragana variant — different characters, not "close".
  Kanji (優花) folds to nothing and still needs its own list entry.
- **Needles of ≤3 characters must score ≥90**, not `STT_WAKE_THRESHOLD`. `partial_ratio` is coarse
  at that length — against three characters the only reachable scores are 100, 80 and 67 — so the
  default 80 means "one character in three is wrong", which in Japanese is a different word: ゆうか
  hits exactly 80 on ユーザー, ユーチューブ and every other ユー… word, while a genuine summons
  scores 100. Thai and romaji variants are 4+ characters and keep the configured threshold.
- **An utterance shorter than the name is scored with `ratio`, not `partial_ratio`.** `partial_ratio`
  gives 100 to any string contained in the other, so a transcript of just "a" or "u" scored 100
  against `yuka` and chimed for a bare "eh" (seen in production, right after a music request). A
  clipped "yuk" still passes (86); a lone letter or "ยู" does not.
- Non-matches are logged at DEBUG **with their score** — tune `STT_WAKE_THRESHOLD` against what
  your speakers' mics actually produce rather than guessing. The score reported on a miss is the
  best *raw* score, even if it was rejected by the short-needle floor.

### TTS — `utils/tts.py`
- `synthesize_speech(text)` → temp MP3 via Edge TTS (`en-US-EmmaMultilingualNeural`, which also speaks Thai).
  The caller plays it and deletes the file.
- Only `/ai voice` uses it; there is no standalone `/tts` command.

### Music Player — `cogs/voice/player.py`
- `/music play|local|pause|resume|stop|skip|seek|previous|nowplaying|loop|queue|volume|leave`, plus a
  button controller embed (`PlayerControls`).
- Per-guild `AudioState` (`PlayerCog.get_state(guild_id)`): `queue` (deque), `current`, `history`
  (last 10), `loop_mode`, `volume` and crossfade state.
- yt-dlp resolves the stream; playback goes through `BufferedAudioSource` / `SeamlessCrossfadeSource`.
  The bot leaves after 180 s idle.
- Other code uses the public methods — `enqueue_query`, `skip_current`, `stop_playback`,
  `remove_from_queue`, `pause_playback`, `resume_playback`, `seek_to`, `rewind_playback`, `set_loop`,
  `set_volume`, `leave_voice` — rather than editing `AudioState` directly. The slash commands are thin
  wrappers over them and raise `UserError` for refusals, so the AI path words them the same way.
- **One `VoiceClient` per guild is shared with `/ai voice`.** `vc.play()` raises while something is
  playing, so Yuuka speaks over a track through its mixer (`add_overlay`, see AI Voice Chat) instead
  of `play()`, and a track must not start while she is speaking (`AIVoiceChatCog._await_speech`).
  The line she speaks after an action races the track's stream lookup, so `_play_next_async` also
  waits (up to 30 s) for the client to go quiet before `play()`; without it the track was dropped
  with "Already playing audio".
- The track prepared for crossfade (`state.crossfade_next`) is out of `state.queue` but still shown as
  queue position 1; count it when indexing the queue the way users see it.

---

## LLM Backend — `utils/ai/`

- **Provider**: [OpenRouter](https://openrouter.ai/) through LangChain core (`langchain-core`, `langchain-openai`). **No LangGraph** — do not add `langchain` or `langgraph`; the loop is hand-written.
- **Agent loop**: `run_agent(history, ctx)` in `agent.py` — the model picks a tool, the result goes back, up to `AGENT_MAX_ROUNDS` model calls (the last without tools). Yields `("thinking" | "plan" | "step" | "status" | "content" | "action" | "done" | "error", payload)` (the first three feed the progress embed, below); `done` is a succeeded turn-ending tool's call and result, which the cogs add to the history as a real tool call (an action-only turn has no text, and a history without it makes the model repeat the request). A `return_direct` tool ends the turn only if it succeeded; a refusal goes back to the model. One reply may hold up to `AGENT_MAX_TOOL_CALLS` calls ("queue it, wait 10 s, then skip"; `wait` pauses without calling the model), run in order; after a failure the rest are skipped. The same read-only call repeated in one reply (`READ_ONLY` in `tools/__init__.py`: search, read, info, queue lookups) runs once and the repeats get a note; actions are never deduplicated, since "play X" twice is a real request.
- **No native tool calls**: the free model has none, so `ToolPromptChatModel` (`tool_calling.py`) describes tools in the prompt and parses `<tool_call>{...}</tool_call>` back into `AIMessage.tool_calls` (gpt-oss's own `<|channel|>…<|call|>` format too). Call text, and text written before a call, never reaches Discord or TTS. A `<tool_response>` the model writes itself is cut off and sent back once. A call nested in harmony markers or with an escaped `<\/tool_call>` is read too, and so is one followed by junk (an extra `}`, a half-written `</tool_call}`): the first JSON value is the call. A call that still cannot be read is dropped together with the text before it ("the song is ready" would claim something that never happened) and the agent retries once, and a reply that is only reasoning ("We need to call tool.") is dropped and retried once with a note. A `[result]` line in an earlier assistant turn is the system's record; the prompt tells the model never to write one.
- **Tools**: standard LangChain `@tool`s in `utils/ai/tools/`, chosen per turn by `tools_for(ctx)`. Per-turn Discord state is passed as `YuukaContext` (`Ctx` alias) via `InjectedToolArg`, so the model never sees it. Adding a tool: write it in a module there, export `TOOLS` and `STATUS`, and gate it in `tools_for`.

| Module | Tools |
|---|---|
| `search.py` | `web_search` |
| `discord_read.py` | `read_messages`, `search_messages` — permissions are the **requester's**, not the bot's (private threads included). Channels they read go in `ctx.channels_used`, and `utils/ai/linker.py` turns her `#name` for them into a clickable `<#id>` (text only; a mention read aloud is digits) |
| `music.py` | `music_play/skip/stop/pause/resume/seek/previous/loop/volume/leave` (via `ai_actions.run_action`; `music_skip` takes a queue `position` or a `song` name, like `/music skip <position>`), `music_now_playing/queue/history/remove`. Volume, loop and pause state ride in the prompt's `[MUSIC]` notice. `music_leave` says goodbye first (she cannot speak once gone) and ends a running `/ai voice` session through `stop_session`, so no "kicked" embed appears. `/music local` has no tool: it needs an attachment |
| `server.py` | `voice_members`, `user_info`, `server_info` — never show who is in a voice channel the requester cannot see |
| `actions.py` | `voice_kick`, `voice_disconnect_timer` — propose only; the `confirm.py` button (requester only) or the requester's spoken yes/no runs them. Offered to anyone in a guild: a missing permission or not being in voice is refused by the tool, because hiding it made the model claim success without calling anything |
| `attendance.py` | `attendance`, `absent` — the `/attendance` and `/absent` reports (`utils/attendance.py`, shared with the commands), posted with their CSV and logged. Read-only, so no confirm button; refused with the reason when the requester is not in a voice channel. Tool results name at most 40 people, the embed and CSV have everyone |
| `capture.py` | `record_start/stop`, `transcribe_start/stop` — the `/record` and `/transcribe` commands, through the same `begin_*`/`end_*` methods as the slash commands. No confirmation (deliberate); starting also posts the command's "started" embed so the room can see it. `/record stop`'s files are delivered in a background task |
| `reminders.py` | `remind_me`, `notify_when_joins_voice` — timers/listeners in `scheduler.py`, **0 LLM requests** while waiting or firing |

- **Progress embed** (`utils/ai/progress.py`, used by `/ai voice` replies): a turn can run tens of seconds with nothing on screen, so people repeat the request and get it twice. `TurnProgress` feeds on `thinking` (round n of `AGENT_MAX_ROUNDS`), `plan` (the calls the model chose, labelled by `utils/ai/tools/labels.py`) and `step` (running / ok / failed / skipped) and keeps one embed with a checklist. It appears after 3 s, or at once for a plan of 2+ steps (a quick answer never shows it), is edited in the background (it never blocks the turn) and deleted when the turn ends. A new tool needs a line in `labels.py`, or it shows under its name. `/ai chat` replies keep their own status embed for now
- **Token budget** (free model: 20 RPM, 50/day without credits): a plain chat is 1 request, a tool turn 2, worst case `AGENT_MAX_ROUNDS`. Button presses, reminders and watches never call the model. Every request carries `max_tokens` = `OPENROUTER_MAX_TOKENS` (4096): without it OpenRouter reserves the model's whole context for the reply and rejects the request when the key's credit cannot cover that.
- **What a request carries**: the system prompt, the `[TOOLS]` section (about 30 schemas, resent every round, so no padding: `_tool_text` strips docstring indentation and JSON spaces), up to `MAX_HISTORY_LENGTH` messages, and every earlier tool result of the turn. Search results are the big item: the table of contents caps each snippet and lists three images, a detail read is capped at 3000 characters, and **the system prompt only names the cached queries** (`[CACHED SEARCHES]`; the model re-reads one with the same query, free). Pasting every cached result there used to put an hour of searches on every request, "play a song" included. Each model call logs `[Usage] prompt N + reply M (reasoning R) tokens` (`stream_usage=True` in `models.py`) — read it before cutting anything else.
- **State**: nothing is persisted (stateless Docker container); pending reminders are lost on restart by design.
- **History squashing**: consecutive messages with the same `role` are merged (required by some instruct models).

---

## Dependency Management (uv)

Key dependencies (versions in `pyproject.toml`):
- Discord: `py-cord[speed,voice]` (from a PR ref in `[tool.uv.sources]`)
- AI: `langchain-core`, `langchain-openai` (no LangGraph), `tavily-python`
- Voice: `faster-whisper`, `livekit-wakeword`, `rapidfuzz`, `edge-tts`, `yt-dlp`, `numpy`
- Images: `pillow`, `pet-pet-gif`, `qrcode`
- System: **ffmpeg** on PATH (playback, recording, `/imgaudio`); the Dockerfile installs it.

- **Add a dependency**: `uv add <package>` (commit `uv.lock` with it)
- **Install / sync**: `uv sync`
- **Install / sync on a GPU box**: `uv sync --extra cuda`
- **Run the bot**: `uv run main.py`
- **Never** use `pip install` directly in this project.

### The `cuda` extra

CTranslate2 ships no CUDA runtime, so a GPU needs cuBLAS and cuDNN 9 from the
`nvidia-*-cu12` wheels. They live in an extra rather than the base dependencies
because they are ~700MB and the CPU deployment box cannot use them.

**A plain `uv sync` uninstalls them**, since it prunes everything outside the
lock's default set. Nothing appears to break when it does: the model still
loads on CUDA and only fails on the first inference, and `utils/stt.py` catches
that and silently falls back to CPU. The symptom is that transcription simply
got slower. On a GPU machine always sync with `--extra cuda`, and check the
startup line — `[STT] Ready — large-v3-turbo / cuda / float16` — if speed drops.

---

## Environment Variables (`.env`)

See **`.env.example`**: every variable `bot/config.py` reads, with its default and a short note.
Copy it to `.env`; never commit `.env`.

---

## Development Workflow

1. `uv sync` (GPU box: `uv sync --extra cuda`)
2. Copy `.env.example` to `.env` and fill in the required values
3. `uv run main.py`, then try the commands in a test server

### Checking a change
There is no test suite. Before committing:
- `uv run python -m compileall -q bot cogs utils` — syntax
- Import every cog (`pkgutil.walk_packages` over `cogs`) — catches broken imports without connecting to Discord
- Logic: a throwaway script with fakes (`unittest.mock`, LangChain's `GenericFakeChatModel`), kept out of the repo
- Discord and voice behaviour still needs a run in a test server; say so if it wasn't done.

### Commits
- Work happens on `yuuka-v3` (the default branch). Don't push or tag unless asked.
- Don't commit until the user has tested the change and says so, small fixes included. Report what
  changed and how to test it, then wait.
- Format: `type(scope): summary`. Types: `feat`, `fix`, `refactor`, `chore`, `docs`. Scopes in use: `ai`,
  `voice`, `music`, `wake`, `deps`. Lowercase, imperative, no trailing period, about 60 characters.
- Body optional: one or two short lines on what changed and why; a human has to review it, so never a
  long description. One commit per meaningful step, each leaving the bot working.
- No `Co-Authored-By` or other attribution lines in commit messages or PR descriptions.

### Releases and deployment
- `uv run bump-my-version bump patch|minor|major` commits and tags `vX.Y.Z`. Full steps, including how
  to undo a bump: `.agents/DEVELOPMENT.md`.
- Pushing a `v*.*.*` tag runs `.github/workflows/docker-build.yml`, which publishes the image to ghcr.io.
- The container is **stateless**: nothing written at runtime survives a restart (no database; reminders
  live in memory). Don't build features that assume persistence.
- Production runs on a CPU-only i5-6500 (see STT Engine).

---

## What NOT to Do

- ❌ Do NOT use `discord.py` patterns — this project uses `py-cord` (the API surface differs)
- ❌ Do NOT use `discord.Color.from_str()` — py-cord uses `discord.Color(0xRRGGBB)` (hex int)
- ❌ Do NOT remove the `aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())` in `bot/bot.py` — `aiodns` (installed by `py-cord[speed]`) uses c-ares which fails DNS resolution on Windows; `ThreadedResolver` uses stdlib `getaddrinfo` as a reliable fallback
- ❌ Do NOT use `commands.Bot` — use `discord.Bot` (we use app commands, not prefix commands)
- ❌ Do NOT hardcode tokens, IDs, absolute machine-specific paths (e.g. `C:/Users/<name>/...`), or any other personal/local info in tracked files — resolve paths relative to a known anchor (repo root, or a script's own location) instead. This extends to filenames/descriptions of gitignored local data files too — a committed doc/script describing a locally-captured file's origin (e.g. "real captured Discord audio") leaks that info even when the binary itself never leaves the machine; use a generic filename and describe its role, not its origin
- ❌ Do NOT let environment/dependency changes (`uv pip install`/`uninstall`, venv creation) go unnarrated — these don't show up as a git diff, so summarize the cumulative state of an environment after a sequence of changes, not just each one in isolation
- ❌ Do NOT use `print()` for logging — use `logger`
- ❌ Do NOT manually add cog imports to `main.py` — the auto-loader handles it
- ❌ Do NOT commit `.env`
- ❌ Do NOT use `pip install` — use `uv add`
- ❌ Do NOT call `voice_client.start_recording()` from a cog — subscribe to `utils.voice_hub` instead; a VoiceClient only supports one sink and the features will fight over it
- ❌ Do NOT peak-normalise STT audio — it amplifies room tone on quiet segments and makes Whisper hallucinate
- ❌ Do NOT remove the wake-word gate from `/ai voice` — without it the bot replies to every sentence spoken in the room
- ❌ Do NOT install `langchain` or `langgraph` — `langchain` v1 pulls in LangGraph; use `langchain-core` / `langchain-openai` only
- ❌ Do NOT let an AI tool act on other people without the `ConfirmActionView` (its button, or the requester's own spoken yes/no), and check the **requester's** permissions, never just the bot's. The one deliberate exception is starting `/record` and `/transcribe` (`capture.py`): no confirmation, but the "started" embed is always posted
- ❌ Do NOT let an AI tool find, list or name a channel the requester cannot see — resolve through `utils/ai/tools/resolve.py`, which treats hidden channels as nonexistent
- ❌ Do NOT use `OLLAMA_*` env vars — nothing reads them; the LLM settings are `OPENROUTER_*`
