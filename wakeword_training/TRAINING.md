# Training Yuuka's acoustic wake-word model

Technical reference for the wake-word training pipeline. For a quick start (what's in this
directory, how to run it), see [README.md](README.md).

**What the model is for.** `/ai voice` used to transcribe *every* utterance in a voice channel
via `utils/stt.py`, then fuzzy-match the transcript in `utils/wake.py` — expensive, since most
utterances aren't addressed to the bot. The acoustic model gates that: it scores raw audio and
decides whether a closed speech segment is worth transcribing at all.

It is a **pre-filter, not the trigger**. The trigger is still the text match. That inverts the
usual wake-word priorities, and it is the single most important thing to know when reading any
number in this document:

- A **miss** silently drops a real summon. This is the failure that matters.
- A **false accept** costs one wasted transcription, which the text match then discards.

Bot integration is done — `utils/wake_acoustic.py`, wired into `cogs/ai/voice_chat.py` ahead of
`transcribe_pcm`. See [Promoting a model](#promoting-a-model) to put a new model behind it.

---

## Current model

**`yuuka_wakeword_v2`** — promoted to `models/wake_word/yuuka_wakeword_v2.onnx`, threshold
**`0.02`** (87.5% recall, ~43 false accepts/hour).

Recall at matched false-positives-per-hour budgets, all three runs scored on one common eval set
(`compare_models.py`, paired bootstrap — every v2 win below is significant):

| FPPH budget | v2 | v1 | POC |
|---|---|---|---|
| 25 | **84.4%** @0.0309 | 81.1% @0.0412 | 55.0% @0.0512 |
| 50 | **88.2%** @0.0178 | 86.0% @0.0239 | 61.8% @0.0382 |
| 91 | **91.0%** @0.0117 | 89.5% @0.0160 | 68.4% @0.0292 |
| 150 | **93.2%** @0.0085 | 92.2% @0.0117 | 74.6% @0.0230 |

Read the high-budget rows — see the pre-filter framing above.

### Why the threshold stayed at `0.02` across the v1→v2 promotion

Measured directly at that threshold rather than interpolated from the table:

| | recall | FPPH |
|---|---|---|
| v2 @ 0.02 | 87.5% | 42.8 |
| v1 @ 0.02 | 87.5% | 64.8 |
| v2 @ 0.012 | 90.8% | 87.0 |

v2's entire gain at `0.02` lands on the false-positive side: same recall as v1, a third fewer
wasted transcriptions, no tuning judgment required. Loosening to `0.012` buys +3.3 points of
recall for double the false accepts — take it only if real summons are observably being dropped.

This is a happy accident of these two curves, **not** a general rule. A threshold is a point on
one model's curve; the same number means a different operating point on a different model.
Re-derive with `compare_models.py` on every promotion — then keep it if it holds up.

### Run history

| run | `n_samples` / `_val` · background / `_val` | steps | verdict |
|---|---|---|---|
| `yuuka_wakeword` (POC) | 300 / 60 · 100 / 20 | 3,600 | Deliberately starved to validate the pipeline. Essentially noise — 20-30 points behind v2 everywhere. Was the promoted model until v2; **not** a rollback target, and no longer kept under `models/wake_word/`. Output still in `output/yuuka_wakeword/`. |
| `yuuka_wakeword_v1` | 10,000 / 2,000 · 200 / 40 | 60,000 total | Real signal, never promoted. Validation accuracy climbed from chance (~50%) to ~76%, confirming the pipeline works. |
| `yuuka_wakeword_v2` | 25,000 / 5,000 · 2,000 / 400 | 120,000 total | **Current.** The scale-up v1's results called for. |
| `yuuka_wakeword_v3` | 25,000 / 5,000 · 2,000 / 400 | 60,000 total | **Rejected — do not promote.** Piper VITS instead of VoxCPM2. Best synthetic numbers of any run (82.9% recall @0.5) and clearly worse in the bot: 17-36 points behind v2 at every matched FPPH budget on a common eval set, and near-blind on unseen TTS engines. See [Why v3 lost](#why-v3-lost-single-tts-overfitting). Its negative set and hyperparameters were genuine improvements and are worth carrying into v4. |

`steps` in the config sets phase 1 only; the real total is `steps + steps/10 + steps/10`.

---

## Running a training run

Everything runs **from the repo root** with `PYTHONUTF8=1` set. Both matter — see
[Gotchas](#gotchas).

```powershell
$env:PYTHONUTF8="1"
$py = "wakeword_training\.venv\Scripts\python.exe"
$cfg = "wakeword_training/configs/yuuka_v2.yaml"

& $py -m livekit.wakeword setup    --config $cfg   # one-time, ~22GB download
& $py -m livekit.wakeword generate $cfg            # synthesize clips (VoxCPM2)
& $py -m livekit.wakeword augment  $cfg            # noise/reverb + feature extraction
& $py -m livekit.wakeword train    $cfg            # train the classifier
& $py -m livekit.wakeword export   $cfg            # .pt -> .onnx
& $py -m livekit.wakeword eval     $cfg            # DET curve, FPPH, recall
```

`setup` takes the config via `--config`; **every other stage takes it positionally.** Not
interchangeable.

Or unattended, with logging to `logs/` — `run_v1_overnight.ps1` / `run_v2_overnight.ps1` run the
whole chain and `Set-Location` to the repo root themselves. Copy one when adding a run.

### Wall time — measured, v2's actual run

| stage | v2 (25,000/5,000 clips, 120,000 steps) |
|---|---|
| `setup` | seconds when already downloaded; hours on a cold `data_dir` |
| `generate` | **19h 20m** |
| `augment` | 30 min |
| `train` | 42 min |
| `export` + `eval` | ~30 s combined |

**`generate` is ~95% of a run.** It calls a full neural TTS model per clip: ~1.6s/clip on GPU
(RTX 3070 measured) vs ~20-30s/clip on CPU, which makes CPU-only generation impractical for a
real dataset. Budget by positive count:

| `n_samples` | ~generate time (positives only) |
|---|---|
| 300 (POC) | ~10 min |
| 10,000 (v1) | ~12 hours |
| 25,000 (v2) | ~20 hours |

Negatives/val/backgrounds add proportionally on top.

### What each stage does

**`setup`** — downloads VoxCPM2 weights, the ACAV100M generic-negative bank (~17GB), and RIRs;
picks up whatever is already in `augmentation.background_paths`. One-time per `data_dir`, safe to
rerun.

**`generate`** — for each clip index, deterministically cycles through `target_phrases`
(`index % len(phrases)`) and, independently, through every `(voice_design_prompt, cfg_value,
inference_timesteps)` combination in `itertools.product` order — **not** random selection. The
only randomness is VoxCPM2's own generation noise, so repeated combos still sound different.
*Resumable*: counts existing `clip_NNNNNN.wav` files per split and continues.

**`augment`** — noise/reverb, then feature extraction through the frozen ONNX mel-spectrogram +
speech-embedding models. Writes `*_features_{train,test}.npy`, shape `(N, 16, 96)`.
**Not resumable** — every invocation deletes *all* `_rN.wav` files and reprocesses from round 0.

**`train`** — 3-phase adaptive training. Checkpointing and validation scale with `steps`
(`validation_interval = steps // 20`, checkpoints only in each phase's last quarter), so a low
`steps` won't silently produce zero checkpoints. Writes `{model_name}.pt` and
`{model_name}_metrics.json`. *Resumable.*

**`export`** — `.pt` → `.onnx`, with a torch/onnxruntime parity check baked in. No GPU needed.

**`eval`** — scores the `.onnx` against the held-out test set plus the ACAV100M pool; writes
`{model_name}_eval.json` and `{model_name}_det.png`. **Do not rank models with it** — see
[Evaluating](#evaluating-and-comparing-models).

---

## Environment

One project-local venv, `wakeword_training/.venv`, built by an idempotent script that verifies
each piece and stops with `FATAL` on the first failure:

```powershell
powershell -File wakeword_training\setup_env.ps1
```

It installs the **stable `livekit-wakeword` release with unmerged
[PR #71](https://github.com/livekit/livekit-wakeword/pull/71) patched in** — multiprocessing for
`augment`/feature-extraction, plus configurable ONNX execution providers. Measured **~90x**
faster `augment` and **~100x** faster feature extraction (394 clips/sec): v1's augment was
estimated at 15-20+ hours without it, v2's took 30 minutes with it. The PR is open, stale
(`CONFLICTING` against `main` since 2026-04-23) and exploratory — but proven on this project's
real dataset.

Two non-obvious things the script handles, both **per-environment** — they must be redone in any
venv built from this PR, not just once globally:

- **`--torch-backend=auto` on the initial install.** Resolves `torch`/`torchaudio` to the CUDA
  build matching your driver in one step. Without it `uv` picks the CPU build even with an NVIDIA
  GPU present, and CPU generation is ~15x slower per clip.
- **`webrtcvad` → `webrtcvad-wheels`, as a separate uninstall-then-install.** PR71 predates that
  Windows fix on `main`, and the plain package is broken here (`pkg_resources` /
  `get_distribution` `AttributeError` on import). Listing both in one install does *not* work:
  `uv` installs them side by side — different package names, nothing tells the resolver one
  substitutes the other — and whichever write lands last wins the shared import path
  non-deterministically (verified; the broken one won).

Verify before trusting it:

```powershell
$py = "wakeword_training\.venv\Scripts\python.exe"
& $py -c "import webrtcvad; print('webrtcvad OK')"
& $py -c "import torch; print(torch.__version__, torch.cuda.is_available())"
& $py -m livekit.wakeword --help
```

`onnxruntime-gpu` does **not** work here — it wants `cublasLt64_13.dll`, absent from
`onnxruntime`'s DLL search path even though torch's bundled CUDA libs exist elsewhere on disk.
Not worth chasing; CPU + multiprocessing is well past being the bottleneck.

---

## Folder layout

| Path | Contents | In git? |
|---|---|---|
| `configs/*.yaml`, `*.py`, `*.ps1` | Config and code — tiny text files | Yes |
| `.venv/` | The training environment | No |
| `data/` | ~22GB shared `setup` downloads (VoxCPM weights, ACAV100M, RIRs) + `backgrounds_chunked/` — **shared across every experiment, never duplicated** | No |
| `output/<model_name>/` | Per-run clips, `.npy` features, `.pt`/`.onnx`, metrics, DET curve | No |
| `logs/` | Unattended-run logs | No |
| `../models/wake_word/` | Promoted models the bot loads | **Yes** |

`data_dir`/`output_dir` are set in each config as `./wakeword_training/...` — relative to **repo
root**, not any machine's absolute path, so configs stay portable across clones. That is why
commands must run from the repo root: those paths resolve against the invoking directory, not the
config file's location.

Per-experiment output is `output_dir / model_name`, so **give each meaningfully different
experiment its own `model_name`**. Reusing one across `generate` runs is how you intentionally
top up a dataset — but `augment` rebuilds from scratch regardless.

---

## The config file

See [`configs/yuuka_v2.yaml`](configs/yuuka_v2.yaml) — the current model's config, commented
throughout with why each value differs from v1.

| Field | Notes |
|---|---|
| `target_phrases` | Script spellings of "Yuuka" — see [One name, many scripts](#one-name-many-scripts-not-many-words) |
| `tts_backend: voxcpm` | Required for Thai/Japanese; Piper is English-only, single locale |
| `voice_design_prompts` | Accent/persona diversity — same section |
| `custom_negative_phrases` | Hand-curated Thai confusables (ยูนะ, ยูริ, ยูกิ, ยูทูบ, command-like phrases), taken from an abandoned openWakeWord attempt — reusing that curation as text, though its pre-rendered WAVs aren't used |
| `n_samples` / `n_samples_val` / `n_background_samples(_val)` | Clips per split — see the run-history table |
| `steps` | Phase 1 only; true total is `steps + steps/10 + steps/10` |
| `model_size` | `medium` on all runs so far — untried lever |
| `augmentation.background_paths` | See [background chunking](#why-the-background-audio-is-591-files) |
| `augmentation.n_workers` / `mp_context` | PR #71 fields. `0` = `os.cpu_count()`; `auto` picks `spawn` on Windows |
| `feature_extraction` / `eval.execution_providers` | PR #71 fields, in preference order; falls back to CPU silently if a provider isn't loadable |
| `batch_n_per_class` | Per-step batch composition. `ACAV100M_sample: 1024` dominates (drawn from the pre-downloaded generic-negative bank); `positive`/`adversarial_negative`/`background_noise: 50` each draw from your generated data |
| `target_fp_per_hour` | Training-time objective (`0.1`). Note this is far stricter than the budget this bot actually deploys at — it shapes training, it is not the operating point |

---

## Evaluating and comparing models

**`compare_models.py` is the ranking tool.** Run it before promoting anything:

```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\compare_models.py --models yuuka_wakeword_v2 <new_run>
```

It fixes an FPPH budget, then compares recall — scoring every model on one common eval set, with
bootstrap confidence intervals and paired significance tests. Accepts run names or `.onnx` paths,
and memoises scores.

**Do not rank models with `eval.json`.** Both of its headline numbers mislead:

- **Recall/FPPH are reported at a fixed threshold of 0.5.** A model whose scores simply sit
  higher shows both higher recall and higher FPPH without being better or worse — it's a
  different point on the same curve. v2 looks like an FPPH regression against v1 for exactly this
  reason (`fpph=0.89 / recall=59%` vs v1's `0.30`), while rescored at matched FPPH it beats v1
  everywhere.
- **AUT** integrates the DET curve over false-positive *rates* from 0 to 1. With 2-second clips
  an FPR of 1% is already ~18 FPPH, so every operating point this bot could deploy at lives in
  the first fraction of a percent of that axis. A discarded v3 tuning sweep scored 18% better on
  AUT while being 20 points worse at every budget under 5 FPPH.

Two caveats on absolute numbers: each row's threshold is set by the top-N negative clips (`#FP`),
so rank on rows where N is in the hundreds; and every figure is per isolated 2-second clip, while
deployment slides a 2s window at 1s stride and takes the max, raising both recall and false
accepts. Use it to compare models, not to predict deployed rates.

**Training-progress chart** — `{model_name}_metrics.json` has the data, no built-in plot:

```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\plot_training_curve.py wakeword_training\output\yuuka_wakeword_v2
```

Takes the metrics JSON or the run's output directory. Writes `<model_name>_training_curve.png`.

**Live mic test** — `test_mic.py` prints a live confidence meter as you speak:

```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py
```

Naive continuous prediction like this pins all CPU cores — ~25x redundant recomputation (96%
window overlap between consecutive predictions) plus `onnxruntime` parallelizing every tiny call
across all cores. Not a bug, just not optimized for polling, and it **doesn't apply to the bot**,
which calls the detector once per already-closed segment.

---

## Promoting a model

The bot does not load out of `output/` — that directory is gitignored and gets rebuilt by the
pipeline, so a fresh clone or a deploy has no way to get the file `utils/wake_acoustic.py` needs.
`models/wake_word/` is a small git-tracked home for promoted models. Each keeps its run's
`model_name` as its filename rather than overwriting one fixed name, so rolling back is a path
change, not a git revert.

1. Copy it in, and `git add` it:
   ```powershell
   cp wakeword_training/output/<model_name>/<model_name>.onnx models/wake_word/<model_name>.onnx
   ```
2. Update **both** `bot/config.py` defaults together — `stt_wake_acoustic_model_path` *and*
   `stt_wake_acoustic_threshold` — committed alongside the model file, so the repo default always
   means "current best version at its own operating point". Take the threshold from
   `compare_models.py` (the row matching the FPPH budget you'll pay in wasted STT calls), **not**
   from `eval.json`'s `optimal_threshold` — that optimises for a standalone trigger, the wrong
   objective for a pre-filter.
3. **Check `.env` for stale `STT_WAKE_ACOUSTIC_MODEL_PATH` / `STT_WAKE_ACOUSTIC_THRESHOLD`
   overrides.** They win over the defaults, and a path pointing at a model that was never
   promoted makes the detector **fail open silently** — one warning line, then it transcribes
   everything. It looks like a working bot with a suddenly large STT bill. This is exactly what
   happened between the v1 and v2 runs.

---

## What to try next

### TODO (agreed, not yet started)

1. **Record real positives.** ~200-500 clips of the actual speakers saying "Yuuka" / "hey Yuuka",
   varied: normal/fast/slow, quiet/loud, near mic and across the room, with music or a fan
   running, ideally several server members. ~20-30 minutes of recording.
   - `_augment_directory` globs **every** `*.wav` in a split, so real clips just get dropped into
     `positive_train/` and are augmented and feature-extracted like synthetic ones. No pipeline
     change needed.
   - Name them `real_NNNN.wav`, **not** `clip_NNNNNN.wav`. They train normally, and
     `eval_per_phrase.py` skips them (its regex only matches `clip_\d+`), which is correct —
     they have no `target_phrases` index.
   - Replicate them to roughly **3-5% of positives**. At 200 clips against 50,000 synthetic they
     are 0.4% and too dilute to shift anything.
2. **Extend `test_mic.py` into a recorder** — key-press captures a 2s clip to `real_NNNN.wav`,
   with a level meter so a too-quiet take is obvious. It already has the pyaudio 16 kHz mono
   plumbing; nothing new to install.
3. **Make `test_mic.py`'s model path a CLI argument.** It is hardcoded to v3, so mic testing has
   been v3-only while the bot runs v2 — the two were never compared on the same utterance.
4. **v4: additive mixing, not 50/50.** Keep all 25,000 VoxCPM2 positives *and* add 25,000 Piper
   on top (`n_samples: 50000`), covering both the train and test splits. A 50/50 split at a fixed
   25,000 total would **halve** the accent-diverse data that is the only reason v2 works on real
   voices. Piper's half costs ~10 minutes; VoxCPM2's is the usual ~20 h.
   Mix must be identical in positives *and* negatives, or the model learns "VoxCPM2 = wake word".
5. **`model_size: large`** — `medium` on every run so far, so its effect is unmeasured, and it
   costs a `train` run (~42 min) rather than a `generate` run.

### Already tried and discarded

**A checkpoint-selection sweep** (confusingly also called "v3" at the time, unrelated to
`yuuka_wakeword_v3`). Won on AUT, lost badly at every budget this bot deploys at, which is what
prompted `compare_models.py`. Scripts and output removed; don't re-run it.

**`yuuka_wakeword_v3` — Piper instead of VoxCPM2.** Do not repeat this. See
[Why v3 lost](#why-v3-lost-single-tts-overfitting).

Whatever the change: give it a new `model_name`, re-run `generate → augment → train → export →
eval`, then rank with `compare_models.py` against `yuuka_wakeword_v2`. A model is only better if
it wins recall at a *matched* FPPH budget — **and only if that budget is measured on audio from a
TTS engine the model never trained on.** See below.

---

## Why v3 lost: single-TTS overfitting

`yuuka_wakeword_v3` swapped VoxCPM2 for Piper VITS. Its own `eval.json` looked like a clear win —
recall **82.9%** @0.5 vs v2's 59.3%, and `optimal_threshold` finally decompressed from 0.01 to
**0.86**. In the bot it was much worse: it would not spike above 0.6 on a real Thai-accented
voice, where v2 fires reliably.

The eval was not wrong, it was **measuring Piper against Piper**. Train and validation split from
the same generator, so the eval was structurally unable to see the problem. Scored on a common
set, each model wins on its own engine's audio and collapses on the other's:

| eval set | v2 | v3 |
|---|---|---|
| v2's held-out (VoxCPM2, accent-diverse) | **84.4%** @25 FPPH | 58.4% |
| v3's held-out (Piper, US English) | 71.1% @25 FPPH | **95.6%** |

Neither model learned "Yuuka" — each learned its TTS engine's acoustics. On **unseen** engines
(the gitignored `wake_multilang_colab.zip` Edge-TTS and `wake_chirp3_th.zip` Chirp3 archives,
whose audio was never training data — only the chirp3 *text* was reused as negatives):

| unseen engine | v2 median | v3 median | v2 >0.5 | v3 >0.5 |
|---|---|---|---|---|
| Edge-TTS (multi-accent) | 0.525 | **0.038** | 52.7% | **3.4%** |
| Chirp3 Thai | 0.846 | **0.450** | 73.0% | 47.0% |
| Chirp3 Thai *negatives* | 0.060 | 0.076 | 19.7% | 21.0% |

v3 fires on 3.4% of Edge-TTS wake words against v2's 52.7% — and its false-accept rate is
slightly *worse*, so it is not trading recall for safety. It is blind to any voice that is not
Piper. This matches the informal check: v2 triggers on Google Translate TTS in English, Thai and
Japanese; v3 does not.

**Root cause.** v2's VoxCPM2 `voice_design_prompts` included `"A Thai-accented English speaker"`
and `"A native Thai speaker"`. Piper's `en-us-libritts-high` is ~900 native American-English
speakers. 900 speakers of one accent is a *narrower* acoustic manifold than 12 personas spanning
several — diversity of manifold beats diversity of speaker count.

**Two lessons that outlive this run:**

- The phoneme sequence is not the accent. `ยูกะ`, `ユーカ` and `yuka` are one phoneme string, which
  is why the romanized Piper spellings were phonetically defensible — but a Thai speaker's
  unaspirated /k/, vowel length and prosody are different *acoustics*, and the frozen
  speech-embedding is sensitive to exactly that.
- **Lowering `max_negative_weight` cannot fix it.** On accent-diverse audio, 51% of v3's positives
  score below its own negatives' 99th percentile — unreachable by any threshold. v3 already uses
  the gentler setting (1000 vs v2's 3000) and still loses at every budget, including 150 FPPH.

openWakeWord would not have helped: takoyaki's pipeline is the same frozen frontend, the same
Piper generator and the same 3-phase trainer, and its report names "dependence on synthetic
speech" and missing "Thai-accented English" as its own top weakness (§36.1), with
`th_hey_tako.wav` scoring 0.342 — the identical failure.

---

## Design decisions

### Why livekit-wakeword, not openWakeWord

openWakeWord was tried first and had "a lot of problems on Windows" — its frozen
feature-extractor models ship as **TFLite**, which has poor-to-no Windows wheel support, plus a
`webrtcvad` dependency needing an MSVC compiler.

[livekit/livekit-wakeword](https://github.com/livekit/livekit-wakeword) fixes this directly: same
underlying approach (frozen mel-spectrogram + Google `speech_embedding` feature extractors,
openWakeWord's own pretrained models) re-exported as **ONNX**, with a Conv-Attention classifier
head instead of a flat DNN and a merged Windows-install fix. Deploy-time footprint is just
`numpy` + `onnxruntime`.

### One name, many scripts, not many words

"Yuuka" is one wake word. `target_phrases` lists multiple *script spellings* (`yuuka`, `yuka`,
`ゆうか`, `ユーカ`, `ยูกะ`, `ยูคะ`) because Thai/Japanese TTS needs native script to phonemize
correctly — not because these are different words.

Accent diversity (a Thai speaker's English vs. a native English speaker's) is handled separately,
by `voxcpm_tts.voice_design_prompts` — natural-language persona descriptions VoxCPM2 uses to vary
the voice, including explicit non-native-accent prompts.

### Why the background audio is 591 files

`augmentation.background_paths` points at `data/backgrounds_chunked/` — 591 ~8-second files, not
the original single 147MB `background_noise_source.wav` (a real recording, gitignored, never
committed).

This matters *because of* multiprocessing. `mix_with_background()` does
`random.choice(self.background_files)` then a full `sf.read()` of the pick. With one file, every
worker's every clip re-reads the same 147MB — with ~20 workers this was verified to stall
completely (all stuck on the same low-level read, no clip finishing). Many small files give
`random.choice()` something to spread across. Same code, just a different-shaped input directory;
single-threaded runs neither need it nor suffer from it.

Regenerate only if the source recording changes:

```powershell
ffmpeg -y -i wakeword_training/data/backgrounds/background_noise_source.wav -f segment -segment_time 8 -c copy wakeword_training/data/backgrounds_chunked/chunk_%04d.wav
```

The source is video-conference audio, not generic room ambience — a deliberate match for this
bot's real deployment (people talking over VOIP in a Discord VC), not a data-quality compromise.

---

## Gotchas

- **`custom_negative_phrases` never reaches the validation split.** The library builds the
  negative pool as `generate_adversarial_phrases(...)` (uncapped) and *then*
  `.extend(config.custom_negative_phrases)` — after the shuffle that happens inside that
  function. Curated phrases therefore always sit in the pool's tail. Clips are assigned
  `phrases[i % len(phrases)]`, and `n_samples_val` (5,000) is smaller than the pool (5,529 for
  v1/v2's targets), so the validation split only ever consumes a prefix and never reaches
  index 5,494+. **Every `fpph` number in v1's and v2's `*_eval.json` was measured against zero
  hard negatives** — treat them as recall-only results, not as a false-accept baseline.
  `wakeword.py` caps the auto pool and interleaves the curated list through it; verify with
  its `--dry-run`, which prints per-split hard-negative coverage.
- **The auto-generated adversarials are mostly not near-misses.** For v2's targets the CMUDict
  search returned 5,494 phrases, nearly all shaped `"<random long word> ka"` (`"accumulation
  ka"`, `"acupuncture ka"`) — because `yuuka` is not in CMUDict and contributes nothing, the
  CJK/Thai spellings contribute nothing (CMUDict is English-only), and only `yuka` matched,
  split into `yu` + `ka`. Scaling `n_samples` multiplies these, not hard negatives.
- **Piper mangles the obvious spellings of "Yuuka", in two different ways.** Both are silent —
  the config looks right and the audio is wrong. Always run `check_pronunciation.py` before
  adding any spelling to `target_phrases`; it gates on both.
  1. `normalize_phrases_for_piper` splits words CMUDict does not know into known subwords
     *before* espeak sees them, so `yuka` synthesizes as `yu ka` — two words with a boundary.
  2. espeak reads a doubled vowel letter as two nuclei, so `yuuka` — which survives
     normalization intact — phonemizes to `/jˈuːjuːkə/`, "yoo-YOO-kuh", three syllables. Every
     `yuu*` spelling does this, including `yuuki`/`yuukai`/`yuukari` as *negatives*, where it
     quietly destroys the near-miss they were chosen for.

  The spellings that actually work are `oo`-based: `yoocah` /jˈuːkə/, `yoocaa` /jˈuːkɑː/,
  `yoocuh` /jˈuːkʌ/, `yoo-cah` /jˈuːkˈɑː/. Onset minimal pairs for negatives follow the same
  pattern — `foocah`, `roocah`, `koocah`, `goocah` (`/ɡ/` vs `/k/` is the tightest pair in the
  set).
- **Piper requires `espeak-ng` on PATH** and the library's error message only documents
  macOS/Linux. On Windows install the `.msi` from
  [espeak-ng releases](https://github.com/espeak-ng/espeak-ng/releases) and confirm
  `espeak-ng --version` resolves; the `generate` stage fails without it. `PYTHONUTF8=1` is
  **required**, not cosmetic, for this path — `_espeak_phonemize` decodes espeak's IPA output
  with the console codepage, and cp1252 raises `UnicodeDecodeError` on it.
- **Piper's duration predictor can run away and OOM the box.** VITS computes
  `w = exp(logw) * length_scale` and clamps it only from *below*
  (`torch.clamp_min`, synthesis.py:301). A rare draw from the stochastic duration predictor
  (logw ~8, roughly 1000x normal) is exponentiated into a ~970-second utterance;
  `y_lengths.max()` then sizes the tensors for the whole batch, so one bad sample inflates every
  clip beside it. Observed: a 64-clip batch requesting 4.4 GB, exhausting 8 GB of VRAM, spilling
  into Windows shared memory and taking system RAM with it. It is **not** a memory leak, and
  lowering `noise_scale_ws` barely helps — measured over 800 draws, natural maxima are 2.9s at
  `noise_w=0.8` vs 3.1s at 0.98. `wakeword.py` installs a guard that bounds *total* utterance
  length (default 8s, `--max-seconds`), rescaling logw proportionally so rhythm is preserved.
  A per-token clamp is the wrong instrument: individual tokens legitimately reach logw 4.9, so
  any cap tight enough to catch runaways fires on ~40% of ordinary clips.
  Clips already written before a crash are fine — `remove_silence` trims them — so `generate`
  can simply be resumed.
- **`PYTHONUTF8=1` before every command.** The CLI's `rich` console output crashes on Windows'
  legacy codepage (`UnicodeEncodeError`).
- **`chcp 65001` too, or logs are mojibake** (`Γûê` instead of `█`). Cosmetic — the underlying
  data is correct UTF-8 — but it persists into any piped log file.
- **Run from the repo root.** Configs use repo-root-relative paths; running from inside
  `wakeword_training/` resolves them wrong.
- **`setup` uses `--config`; every other stage takes the config positionally.**
- **`augment` is not resumable** (deletes all `_rN.wav` files every invocation). `generate` and
  `train` are.
- **`uv` resolves CPU-only `torch` by default** even with a GPU present — a **per-environment**
  default, so `--torch-backend=auto` is needed on *every* venv/tool install independently.
- **PR #71 reintroduces broken `webrtcvad`** — must be manually swapped for `webrtcvad-wheels`
  in any environment built from it (see [Environment](#environment)).
- **Feature extraction is CPU-only in the base library** (hardcoded `CPUExecutionProvider`).
  PR #71 makes it configurable, but `onnxruntime-gpu` still can't reach CUDA here. CPU +
  multiprocessing is fast enough regardless.
- **Parallel `augment` + a single background file = I/O contention**, not a code bug — see
  [background chunking](#why-the-background-audio-is-591-files).
- **PowerShell 5.1: `$ErrorActionPreference = "Stop"` plus `2>&1` kills successful runs** — any
  stderr line from a native process, even a harmless warning, becomes a terminating error. Use
  `"Continue"` and check `$LASTEXITCODE` explicitly (see `run_v2_overnight.ps1`).
- **A non-raw Python docstring containing a Windows path** like `...\uv\tools\...` breaks with
  `SyntaxError: (unicode error) 'unicodeescape' codec...` — `\u` parses as a unicode escape. Use
  `r"""..."""` for any string with literal Windows paths.
