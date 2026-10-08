# Plan: score every 80 ms hop in the acoustic wake gate

Status: **implemented 2026-10-08 (uncommitted, waiting for the user's test), with two changes from
this plan.** (1) The default is v2 at 0.6, not v3 at 0.4: after implementing, v3 turned out to fire
on "silence, then any short sound" (music or voices alone passed about 60% at 0.4; quiet room noise
in front of the name dropped it to 0%), and v3 had never been shown better than v2. (2) A dev-only
`STT_WAKE_ACOUSTIC_COMPARE_PATH` logs a second model's scores on the same audio. The rest of this
file is the original plan; its threshold numbers are for v3. Written 2026-10-08 from the 2026-10-04/05 test-session logs and an
offline experiment. Read `CLAUDE.md` and `.agents/AGENTS.md` first; their rules apply (no commit until
the user has tested, commit format, persona, no machine paths in tracked files).

## Goal

`utils/wake_acoustic.py` decides whether a speech segment is worth sending to STT. For every
segment of 2 s or less it scores exactly **one** classifier window, the one ending at the
segment's last sample. Every "ยูกะ" people say is such a segment (0.6-1.6 s). Make it score a
window ending at **every 80 ms hop** of the segment, whatever its length, and move the default
threshold to fit the new scores. One file of logic, plus config, `.env.example` and docs.

## Why (evidence)

### What the code does today

```python
if audio.size < _MIN_SAMPLES:                      # _MIN_SAMPLES = 2 s
    audio = np.pad(audio, (_MIN_SAMPLES - audio.size, 0))
embeddings = ...                                   # 2 s of audio -> exactly 16 embeddings
n = embeddings.shape[0] - 16 + 1                   # -> n == 1
```

Measured: any input of 2.00 s or less gives 16 embeddings and one window. 2.08 s gives 2,
2.5 s gives 7, 4 s gives 26. The module docstring says it scores every hop; for short segments
it never has.

The models were trained with the word ending 0-200 ms before the end of the 2 s window
(`livekit.wakeword.data.augment.align_clip_to_end`). A Discord segment is the received packets
back to back (`utils/voice_hub.py`), and Discord keeps sending audio for a moment after the
speaker stops, longer when music or noise keeps the mic open. That trailing audio moves the word
away from the one position that is scored, and the score collapses.
`wakeword_training/test_mic.py` streams and scores every 80 ms, which is why v3 looked good in
the mic test and is flaky in the bot.

### Bot log, 2026-10-04 23:30 to 10-05 01:52 (one speaker, threshold 0.1 then 0.3)

| | summons | first-try success | mean tries per summon |
|---|---|---|---|
| no music | 21 | 6 | 4.1 |
| bot music playing | 20 | 2 | 5.3 |

77-88% of the failed tries were rejected by the acoustic gate at a median score of 0.05-0.08
(near zero, not "almost"). The rest passed the gate and were misheard by STT. Scores are
bimodal: a take either scores 0.5-0.9 or near 0. This is what a position problem looks like.

### Offline experiment (TTS clips the models never trained on)

300 Chirp3 Thai "ยูกะ" clips; segment = 100 ms lead + word + N ms of quiet audio after it,
optionally with music or voices behind and an Opus 64 kbps round trip. v3, recall at 0.3:

| condition | today (one window) | every 80 ms |
|---|---|---|
| word at the very end | 65% | 95% |
| +300 ms after the word | 47% | 95% |
| +500 ms | 14% | 96% |
| +800 ms | 0% | 96% |
| Opus, music 0 dB, +300 ms | 43% | 98% |
| Opus, voices 0 dB, +300 ms | 44% | 98% |
| Opus, music 5 dB, +800 ms | 1% | 98% |

The intended flow stays: say the name, hear the chime, then speak the command (one-breath
timing is hard to predict, which is why the chime exists). The fix is for that bare name. A side
effect: a name at the start of a 4.7 s segment ("ยูกะ" then other sound) scored 0.008 today and
0.72 with the fix, so someone who does say "ยูกะ เปิดเพลง ..." in one breath is no longer blocked
by the gate (`voice_chat.py` already answers a name plus request directly). Do not build anything
around one-breath commands.

These are TTS voices. Real Thai voices score lower; the experiment shows the scoring loss, not
real-voice recall.

### The cost: more segments reach STT

At a fixed threshold, scoring every hop lets more non-name segments through. v3 with the fix,
400 Chirp3 negatives (289 near-misses such as ยูกิ / ยูกัน / อยู่ค่ะ, 111 ordinary sentences):

| threshold | Thai recall, worst / mean condition | ordinary sentences passed: quiet, music behind, voices behind | near-misses passed (same order) |
|---|---|---|---|
| 0.3 | 95% / 97% | 30%, 72%, 70% | 86%, 95%, 97% |
| **0.4** | 92% / 95% | 16%, 57%, 55% | 79%, 91%, 92% |
| 0.5 | 89% / 92% | 14%, 41%, 46% | 71%, 88%, 87% |

Each pass is one Groq request (free tier: 20 per minute, 2,000 per day; on a 429 the bot falls
back to slow local STT). Long segments were already scanned, so the increase is in short ones.
At matched recall the fix lets through far fewer false triggers than today: today needs a
threshold of 0.003 to keep 95% of the clips, where 57% of ordinary sentences pass.

## Scope

In:

1. `utils/wake_acoustic.py`: the scoring change, a DEBUG line, the module docstring.
2. Default threshold 0.1 -> 0.4: `bot/config.py` (field default and the `from_env()` default
   string) and `.env.example`.
3. Docs: `.agents/AGENTS.md` and `wakeword_training/TRAINING.md` (see Change 4).

Out (do not do these here):

- `cogs/ai/voice_chat.py`: `detect()` keeps its signature, so the gate and its log lines stay as
  they are.
- The user's `.env`. It currently sets `STT_WAKE_ACOUSTIC_THRESHOLD=0.3`, which overrides the new
  default. Tell the user; do not edit it.
- Model files, retraining, switching to v2, an STT prompt, a segment recorder. Separate work.

## Change 1: `utils/wake_acoustic.py`

Replace the constants and `_predict_max`, and log in `detect`. Keep the private-attribute access
(`model._mel_frontend`, `model._speech_embedding`, `model._classifiers`) exactly as today.

```python
_SAMPLE_RATE = 16_000
_WINDOW_SAMPLES = 2 * _SAMPLE_RATE  # one classifier window: 16 embeddings, about 2 s
_HOP_SAMPLES = 1_280  # one embedding step: 8 mel frames of 10 ms, i.e. 80 ms
_MIN_EMBEDDINGS = 16  # classifier input length
```

```python
    def _predict_max(self, audio: np.ndarray) -> tuple[float, float, float, int]:
        """Score a window ending at every 80 ms hop of ``audio``.

        Returns (best score, score of the window ending at the last sample,
        seconds from the best window's end to the segment's end, windows scored).
        """
        assert self._model is not None
        model = self._model

        # A full window of silence in front, rounded up so the padded length is a whole
        # number of hops: then the last window ends exactly at the segment's last sample
        # (the window the old code scored), and every earlier hop ends a window too.
        lead = _WINDOW_SAMPLES + (-audio.size) % _HOP_SAMPLES
        audio = np.concatenate([np.zeros(lead, dtype=np.float32), audio.astype(np.float32, copy=False)])

        mel = model._mel_frontend(audio)
        embeddings = model._speech_embedding.extract_embeddings(mel)[0]
        if embeddings.shape[0] < _MIN_EMBEDDINGS:
            return 0.0, 0.0, 0.0, 0

        n = embeddings.shape[0] - _MIN_EMBEDDINGS + 1
        batch = np.stack(
            [embeddings[i : i + _MIN_EMBEDDINGS] for i in range(n)], axis=0
        ).astype(np.float32)

        scores = np.zeros(n, dtype=np.float32)
        for session, input_name in model._classifiers.values():
            scores = np.maximum(scores, session.run(None, {input_name: batch})[0][:, 0])
        best = int(np.argmax(scores))
        return float(scores[best]), float(scores[-1]), (n - 1 - best) * _HOP_SAMPLES / _SAMPLE_RATE, n
```

In `detect`, replace the scoring line:

```python
        best, at_end, before_end, windows = await asyncio.to_thread(self._predict_max, audio)
        logger.debug(
            f"[Wake Acoustic] best {best:.3f} on the window ending {before_end:.2f}s before "
            f"the segment end (end window alone {at_end:.3f}, {windows} windows)"
        )
        return best >= config.stt_wake_acoustic_threshold, best
```

The "end window alone" number is what today's code would have scored for any segment of 2 s or
less. Keep it: it lets the user compare old and new behaviour on real voices from one session
log. Remove `_MIN_SAMPLES` and grep the repo for any other use first.

Rewrite the docstring section "Why every 80 ms hop" to say: the classifier fires when the word
ends at the window's trailing edge; a segment of 2 s or less used to get one window ending at its
last sample, so audio after the name (Discord's tail, music holding the mic open) hid it; the
segment is now led by a full window of silence, rounded to a whole number of hops, so a window
ends at every 80 ms hop, including near the start of a long segment. Mention the cost (below)
in one line. Keep the paragraph about reaching into private frontends.

## Change 2: threshold default 0.1 -> 0.4

- `bot/config.py`: `stt_wake_acoustic_threshold: float = 0.4`, and the `from_env()` default
  `os.getenv("STT_WAKE_ACOUSTIC_THRESHOLD", "0.4")`. Add a short comment that the value is for
  every-hop scoring.
- `.env.example`: `STT_WAKE_ACOUSTIC_THRESHOLD=0.4` with a comment such as
  `# every 80 ms hop is scored; raise it if Groq rate limits (429) show up in a busy call`.

Why 0.4: see the cost table. It keeps nearly every take that already passed (in the session log,
39 of 46 confirmed summons scored 0.4 or more under the old scoring, and the new score is never
lower), and keeps short ordinary sentences in a quiet room at about 16%. It is a starting point
to tune in the server, not a measured optimum. Real voices score lower than TTS, so do not go
higher before the user has tested.

## Change 3: nothing else in code

`cogs/ai/voice_chat.py` already logs `No acoustic wake hit ... (score X < thr)` and
`Acoustic wake hit ... (score X >= thr)`. They now show the best score.

## Change 4: docs

- `.agents/AGENTS.md`, "The signal waits for the transcript": the figures "v3 scores 0.4-0.6 at
  best on a clear Thai voice, 0.0-0.1 with noise" were measured when short segments got one
  window. Add that qualifier; do not invent new figures. In the AI Voice Chat section, add one
  bullet: the gate scores a window ending at every 80 ms hop (`utils/wake_acoustic.py`, full
  window of silence in front); before this, a segment of 2 s or less got one window ending at its
  last sample and audio after the name hid it.
- `wakeword_training/TRAINING.md`, "v3 in a real group call (2026-10-04)": add one line that those
  scores came from the single-window scoring, fixed on <date>, so v2 vs v3 vs v4 must be compared
  with the new scoring.
- No `CLAUDE.md` change: no rule changes.

## Testing

### Automated (no Discord)

1. `uv run python -m compileall -q bot cogs utils`
2. Import every cog (`pkgutil.walk_packages` over `cogs`), as in AGENTS.md "Checking a change".
3. A throwaway script **outside the repo** (temp dir), run from the repo root with
   `uv run python <path>` so `bot.config` loads `.env`. Call the real
   `utils.wake_acoustic.acoustic_wake.detect(pcm)` with 48 kHz stereo s16le PCM (what voice_hub
   produces). Make the PCM with ffmpeg:
   `ffmpeg -v error -i clip.wav -f s16le -ar 48000 -ac 2 pipe:1`.
   Test audio: `wake_chirp3_th.zip` in the repo root (gitignored, local only) has
   `dataset_chirp3/positive/yuka_*.wav` (Thai TTS "ยูกะ") and `negative/neg_*.wav`. Extract it
   to the temp dir, never into the repo. Keep a copy of the old `_predict_max` in the script to
   compare against. Check:
   - **Never lower:** for 30 positive clips, each with 0, 200, 400 and 700 ms of quiet audio
     appended (about -60 dBFS noise, as PCM), new best >= old score - 1e-5. The prototype
     measured a max difference of 2e-7.
   - **Tail tolerance:** median new vs old score at 0 / 300 / 500 / 800 ms appended. Expect new to
     stay roughly flat (about 0.9) while old falls toward 0.
   - **Name first:** one clip followed by 3 s of other sound: new high, old near 0.
   - **Silence:** all-zero PCM and low noise score below 0.02 (measured 0.002-0.010).
   - **Edge cases unchanged:** empty PCM gives `(False, 0.0)`; with
     `STT_WAKE_ACOUSTIC_ENABLED=false`, `(True, 1.0)`.
   - **Time:** `_predict_max` on 1 s, 5 s and 20 s of audio. Prototype on the dev PC: 1 s
     28 -> 75 ms, 5 s 126 -> 213 ms, 20 s 604 -> 790 ms. Report your numbers; the production box
     (i5-6500) will be slower. It runs in `asyncio.to_thread`, so it adds latency to that segment
     only.
4. Delete the throwaway script and extracted audio afterwards.

### Manual, in the test server (the user does this; say it was not done)

Set `STT_WAKE_ACOUSTIC_THRESHOLD=0.4` in `.env` (or remove the line), run `uv run main.py`,
start `/ai voice`, and keep DEBUG logging on. For each case, say "ยูกะ" about 10 times and count
chimes. From the `[Wake Acoustic]` lines, count how often the end-window score was below the
threshold while the best score was above it (summons the old code would have dropped):

1. Alone, quiet room, Discord noise suppression on, then off.
2. Alone, bot music playing through speakers (no headphones).
3. Group call with talk and music: count `Acoustic wake hit` lines per minute and watch for
   `[STT] Groq rate limit hit`. More than about 15 passes a minute, or any 429, means raise the
   threshold by 0.1.
4. Optional side-effect check: "ยูกะ เปิดเพลง <song>" in one breath now gets past the gate.
   The normal flow (name, chime, command) is what cases 1-3 test.
5. Optional: the same with `STT_WAKE_ACOUSTIC_MODEL_PATH=models/wake_word/yuuka_wakeword_v2.onnx`.
   On TTS clips with this scoring, v2 let through fewer ordinary sentences than v3 at the same
   recall. Real voices decide.

## Commit (only after the user has tested and says so)

```
fix(wake): score every 80 ms hop of short segments

A segment under 2 s got one window ending at its last sample, so audio after the
name hid it. Default threshold 0.1 -> 0.4 for the new scores.
```

One commit for code, config, `.env.example` and docs. No attribution lines. Do not push.

## What to report to the user

Files changed, the automated results (the five checks, with numbers), that `.env` still says 0.3
and overrides the new default, the manual test list above, and that nothing was tested in
Discord.

## Found during the investigation, not part of this fix

- **TRAINING.md TODO #1 names real clips `real_NNNN.wav`, which the pipeline ignores.**
  `augment` round 0 only reads `clip_\d{6}.wav` and feature extraction only reads
  `clip_\d{6}_r\d+.wav` (livekit-wakeword 0.2.1.dev11 in the training venv). Real or cloned
  clips must be named `clip_9NNNNN.wav` and added after `generate` has finished (`generate`
  counts `clip_` files to decide where to resume).
- **Every model so far trained on TTS only**, with no real Thai-accented voice. Whisper often
  writes the user's real "ยูกะ" as โยกะ / โยคะ / ヨガ / Yoka / "You got it", while v3's negative
  list trains "yoga", "yuga", "yoogah", "hey yoga" and "you got" as not the wake word.
- **STT is the other failure point:** 9-22% of failed tries passed the gate and were misheard
  ("You got it.", "ยุคค่ะ", "โอเค"). `utils/stt.py` sends no `prompt` to Groq.
