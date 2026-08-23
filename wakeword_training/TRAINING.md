# Training Yuuka's acoustic wake-word model

## Goal

Gate the current text-based wake-word matcher (`utils/wake.py`) behind an acoustic model that
listens to raw audio and decides whether a closed speech segment is worth transcribing at all,
**before** paying for a full STT call. Previously, every utterance spoken in a voice channel got
fully transcribed (local `faster-whisper` or the Groq API) via `utils/stt.py`, then
`utils/wake.py` fuzzy-matched the transcript — expensive and wasteful, since most utterances
aren't addressed to the bot at all.

**Bot integration is done** (`utils/wake_acoustic.py`, wired into `cogs/ai/voice_chat.py` ahead
of `transcribe_pcm`) — see "Promoting a model to run" near the bottom. This document covers the
training side: how the model gets built, and how to build a better one.

## Why livekit-wakeword, not openWakeWord

openWakeWord was tried first and had "a lot of problems on Windows" — its frozen
feature-extractor models ship as **TFLite**, which has poor/no Windows wheel support, plus a
`webrtcvad` dependency needing an MSVC compiler.

[livekit/livekit-wakeword](https://github.com/livekit/livekit-wakeword) fixes this directly:
same underlying approach (frozen mel-spectrogram + Google `speech_embedding` feature
extractors, openWakeWord's own pretrained models) but re-exported as **ONNX** instead of
TFLite, a Conv-Attention classifier head instead of a flat DNN, and a merged Windows-install fix
(`webrtcvad` → `webrtcvad-wheels`, fixed espeak UTF-8 decoding). Deploy-time footprint is just
`numpy` + `onnxruntime`.

## One name, multiple accents, not multiple words

"Yuuka" is one wake word. The `target_phrases` list has multiple *script spellings*
(`yuuka`, `yuka`, `ゆうか`, `ユーカ`, `ยูกะ`, `ยูคะ`) because Thai/Japanese TTS needs native
script to phonemize correctly — not because these are different words. Accent diversity
(a Thai speaker's English pronunciation vs. a native English speaker's) is handled instead by
`voxcpm_tts.voice_design_prompts` — natural-language persona descriptions VoxCPM2 uses to vary
the voice, including explicit non-native-accent prompts.

## Setup — one consolidated venv (CUDA + multiprocessing, both verified working)

Everything needed lives in a single project-local venv, `wakeword_training/.venv`, built from
the **stable `livekit-wakeword` release plus an unmerged upstream PR patched in**:
[github.com/livekit/livekit-wakeword/pull/71](https://github.com/livekit/livekit-wakeword/pull/71)
adds optional multiprocessing to `augment`/feature-extraction and configurable ONNX execution
providers — measured **~90x** faster `augment` (2.3 → 178 clips/sec on a 32-core box; on this
machine, augment for the full v1 dataset went from an estimated 15-20+ hours to a few minutes)
and **~100x** faster feature extraction (3.5 → 394 clips/sec, verified). The PR is open,
unmerged, and stale (last touched 2026-04-23, currently shows `CONFLICTING` against `main`) —
exploratory, not an official release, but empirically proven on this project's real dataset.

**Build it with `wakeword_training/setup_env.ps1`** — a real, idempotent script, not manual
copy-paste instructions:
```powershell
powershell -File wakeword_training\setup_env.ps1
```
It creates the venv, installs the PR71 branch with torch resolved straight to CUDA, applies the
one remaining mandatory fix below, verifies everything independently, and stops with a `FATAL`
message + exit code on the first thing that fails — it does not silently continue past a broken
step. It uses only repo-relative paths (via `$PSScriptRoot`), so it works after a fresh clone on
any machine without editing anything in it first.

What it does, spelled out (for understanding what's happening — you don't need to run these by
hand, the script does it):
```powershell
uv venv wakeword_training/.venv --python 3.12
uv pip install --python wakeword_training/.venv/Scripts/python.exe --torch-backend=auto "livekit-wakeword[train,eval,export,voxcpm,listener] @ git+https://github.com/livekit/livekit-wakeword@refs/pull/71/head"
```
`--torch-backend=auto` on this **initial** install (verified, not assumed — tested in an
isolated venv) resolves `torch`/`torchaudio` straight to the CUDA build matching your driver, no
separate reinstall needed. `uv pip install` resolves the plain CPU build by default even with an
NVIDIA GPU present otherwise — a per-environment default; the flag needs to be present, but
doesn't need to be a follow-up step. `generate` calls a full neural TTS model (VoxCPM2) per clip
— **~20-30s/clip on CPU vs ~1.6s/clip on GPU** (RTX 3070 measured); CPU-only generation for a
real dataset is impractical (17+ hours for 4,000 clips alone).

**One fix that genuinely can't be folded into the install above**: PR71's branch point predates
a later Windows-compat fix on `main` that swapped `webrtcvad` → `webrtcvad-wheels`. Installing
the PR as-is pulls plain `webrtcvad`, which is broken in this environment
(`AttributeError: module 'pkg_resources' has no attribute 'get_distribution'` on import — the
old package is incompatible with modern `setuptools`). Tested whether listing
`webrtcvad-wheels` alongside the initial install avoids the extra step (the same trick that
works for `torch`) — it does not: `uv` installs **both** packages side by side, since they're
different package names with no way for the resolver to know one substitutes the other, and
whichever's file write lands last wins the same import path non-deterministically (verified: the
broken one won in testing). An explicit uninstall-then-install is the only reliable fix:
```powershell
uv pip uninstall --python wakeword_training/.venv/Scripts/python.exe webrtcvad
uv pip install --python wakeword_training/.venv/Scripts/python.exe webrtcvad-wheels
```

Verify before trusting the environment:
```powershell
wakeword_training/.venv/Scripts/python.exe -c "import webrtcvad; print('webrtcvad OK')"
wakeword_training/.venv/Scripts/python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
wakeword_training/.venv/Scripts/python.exe -m livekit.wakeword --help
```

`onnxruntime-gpu` was also tried (for feature-extraction/eval GPU acceleration) but does **not**
work here — it needs `cublasLt64_13.dll`, which isn't on `onnxruntime`'s DLL search path even
though `torch`'s own bundled CUDA libraries exist elsewhere on disk. Not worth chasing: CPU +
multiprocessing already measured 394 clips/sec, well past the point of being a bottleneck.

Set `PYTHONUTF8=1` before every command below — the CLI's `rich`-based console output crashes on
Windows' legacy codepage otherwise (`UnicodeEncodeError` on a stray unicode character in help
text or log output).

## Folder layout

- **Config and code live in the repo**: `wakeword_training/configs/*.yaml`, `*.py`, `*.ps1` —
  tiny text files, tracked in git.
- **`wakeword_training/.venv/`** — the consolidated environment above. Gitignored (never commit
  a venv).
- **Heavy data lives in `wakeword_training/data/` and `wakeword_training/output/`**, set via
  each config's `data_dir`/`output_dir` fields as `./wakeword_training/...` — relative to
  **repo root**, not this (or any) machine's absolute path, so the config stays portable across
  clones/users. This means **every command below must be run with the repo root as the current
  directory** — `./wakeword_training/data` resolves against whatever directory the CLI is
  invoked from, not the config file's own location, so running from inside `wakeword_training/`
  itself would resolve wrong. `run_v1_overnight.ps1` enforces this itself
  (`Set-Location` to repo root at the top); do the same manually (`cd` to repo root) before any
  ad-hoc command. Both `data/` and `output/` are gitignored regardless. `data_dir` holds the ~22GB shared `setup` downloads (VoxCPM weights, ACAV100M,
  RIRs) plus `backgrounds_chunked/` (591 ~8s files split from a real background-noise
  recording, see below) — **shared across every experiment, never duplicated**. `output_dir` holds the
  per-experiment stuff.
- **Per-experiment folder is `output_dir / model_name`** (see `config.py`: `model_output_dir
  = Path(output_dir) / model_name`). Every split's clips, extracted `.npy` features, the
  trained `.pt`/`.onnx`, metrics JSON, and DET curve PNG all live there. **Give each
  meaningfully different experiment its own `model_name`** (e.g. `yuuka_wakeword_poc`,
  `yuuka_wakeword_v1`) so runs don't overwrite each other. Reusing the same `model_name` across
  `generate` runs is how you *intentionally* resume/top-up a dataset — but note `augment` is
  **not** resumable (see Gotchas) — rerunning it deletes and rebuilds all augmented output from
  scratch for that `model_name`, regardless of `generate`'s own resumability.

## Why the background audio is chunked into 591 files, not one

`augmentation.background_paths` points at `wakeword_training/data/backgrounds_chunked/` — 591
~8-second files, not the original single 147MB `background_noise_source.wav` (a real recorded
noise source, still the ultimate origin — kept local-only, gitignored, never committed). This matters specifically *because* of
multiprocessing: `mix_with_background()` does `random.choice(self.background_files)` then a
full `sf.read()` of whatever it picked. With one background file, every worker's every clip
reads that same 147MB file — with ~20 parallel workers, this was verified to cause severe I/O
contention (all workers observed stuck on the exact same low-level file-read call, no clip
completing). Splitting into many files gives `random.choice()` more to pick from, so parallel
workers mostly land on different, much smaller files instead of colliding — same code, no
logic changes, just a different-shaped input directory. Single-threaded runs don't need this
(no collision possible with one worker), but there's no downside to it either.

To regenerate (only needed if the source recording changes):
```powershell
ffmpeg -y -i wakeword_training/data/backgrounds/background_noise_source.wav -f segment -segment_time 8 -c copy wakeword_training/data/backgrounds_chunked/chunk_%04d.wav
```

## The config file

See `wakeword_training/configs/yuuka_v1.yaml` for the full file. Key fields:

- `target_phrases` — script spellings of "Yuuka" (see accent note above)
- `tts_backend: voxcpm` — required for Thai/Japanese (Piper is English-only, single locale)
- `voice_design_prompts` — accent/persona diversity (see accent note above)
- `custom_negative_phrases` — hand-curated Thai confusable words/phrases (ยูนะ, ยูริ, ยูกิ,
  ยูทูบ, command-like phrases, etc.), sourced from an earlier abandoned openWakeWord attempt's
  `wake_chirp3_th.zip/metadata.csv` (negative-labeled rows' `canonical_text`, deduplicated) —
  reusing that curation effort as text even though the pre-rendered WAV files aren't used
- `n_samples` / `n_samples_val` / `n_background_samples(_val)` — clips per split. v1 used
  10,000/2,000/200/40 (the library's own class defaults); a POC run before it used 300/60/100/20
  purely to validate the pipeline
- `steps` — training steps for phase 1; actual total is `steps + steps/10 + steps/10` (3
  phases). v1 used 50,000 (→ ~60,000 total)
- `augmentation.background_paths` — see chunking note above
- `augmentation.n_workers` / `mp_context` — PR #71 fields. `0` = `os.cpu_count()`, `auto` picks
  `spawn` on Windows
- `feature_extraction.execution_providers` / `eval.execution_providers` — PR #71 fields,
  requested in preference order; falls back silently to CPU if the earlier ones aren't actually
  loadable (see the `onnxruntime-gpu` note above)
- `batch_n_per_class` — per-training-step batch composition; `ACAV100M_sample: 1024` dominates
  (draws from the large pre-downloaded generic-negative bank), `positive`/`adversarial_negative`/
  `background_noise: 50` each draw from your own generated data

## Pipeline

Run each step from the repo root, with `PYTHONUTF8=1` set, via the consolidated venv:

```powershell
$env:PYTHONUTF8="1"
$py = "wakeword_training\.venv\Scripts\python.exe"

& $py -m livekit.wakeword setup    --config wakeword_training/configs/yuuka_v1.yaml  # one-time, ~22GB download
& $py -m livekit.wakeword generate wakeword_training/configs/yuuka_v1.yaml           # synthesize clips (VoxCPM2)
& $py -m livekit.wakeword augment  wakeword_training/configs/yuuka_v1.yaml           # noise/reverb + feature extraction
& $py -m livekit.wakeword train    wakeword_training/configs/yuuka_v1.yaml           # train the classifier
& $py -m livekit.wakeword export   wakeword_training/configs/yuuka_v1.yaml           # .pt -> .onnx
& $py -m livekit.wakeword eval     wakeword_training/configs/yuuka_v1.yaml           # DET curve, FPPH, recall
```

Note `setup` takes the config via `--config`; every other stage takes it positionally — not
interchangeable, mixing them up is a common mistake (see Gotchas).

### `setup`
Downloads VoxCPM2 weights, the ACAV100M generic-negative feature bank (~17GB), RIRs, and picks
up anything already in `augmentation.background_paths`. One-time per `data_dir`; safe to rerun
(skips what's already there).

### `generate`
For each clip index it deterministically cycles through `target_phrases` (`index %
len(phrases)`) and, independently, through every `(voice_design_prompt, cfg_value,
inference_timesteps)` combination (`itertools.product` order) — **not random selection**. The
only randomness is VoxCPM2's own generation noise, so identical parameter combos still produce
different-sounding clips each time. `n_samples` just sets how many times this loop runs.

**Resumable**: counts existing `clip_NNNNNN.wav` files in each split folder before starting,
and continues/skips accordingly. Safe to kill and rerun.

Time budget (GPU, ~1.6s/clip measured on an RTX 3070; ~20-30s/clip on CPU if the torch fix above
was skipped):
| `n_samples` | ~generate time (positives only) |
|---|---|
| 300 (poc) | ~10 min |
| 4,000 | ~1.8 hours |
| 10,000 (v1) | ~4.5 hours |
| 25,000 (library class default) | ~11 hours |
Negatives/val/backgrounds add proportionally more.

### `augment`
Applies noise/reverb augmentation, then extracts features through the frozen ONNX
mel-spectrogram + speech-embedding models. With the consolidated venv's multiprocessing +
chunked backgrounds: **verified fast** (v1's full ~72,700 augmentation passes across 3 rounds
finished in minutes; feature extraction ran at 394 clips/sec). Saves `*_features_{train,test}.npy`
files, shape `(N, 16, 96)`.

**Not resumable** — every invocation deletes *all* existing `_rN.wav` augmented files first,
then reprocesses everything from round 0, regardless of how much progress existed. Killing and
rerunning `augment` throws away all prior augment progress (unlike `generate`/`train`).

### `train`
3-phase adaptive training (phase 1 = `steps`, phase 2/3 = `steps/10` each). Checkpointing and
validation are **proportional to `steps`**, not an absolute step count (`validation_interval =
steps // 20`, checkpoints only save in each phase's last quarter) — lowering `steps` doesn't
risk "zero checkpoints saved." Saves `{model_name}.pt` and `{model_name}_metrics.json` (a
JSON array of validation snapshots — step/phase/fpph/recall/accuracy — see "Charting" below).
Unaffected by PR #71 (the PR doesn't touch `train.py`) — behaves identically regardless of
which environment runs it.

### `export`
Converts the `.pt` to `.onnx` (with a torch/onnxruntime parity check baked into the
`torch.onnx.export` pipeline). Fast, no GPU needed.

### `eval`
Runs the exported `.onnx` against the held-out test set + the large ACAV100M validation pool,
computes AUT/FPPH/recall, and saves **`{model_name}_det.png`** — a DET curve (False Positive
Rate vs. False Negative Rate across thresholds) with metrics annotated. Also saves
`{model_name}_eval.json`.

## Charting training progress

No built-in "loss/accuracy over time" plot, but the data exists in `{model_name}_metrics.json`
(written by `train`). Use `wakeword_training/plot_training_curve.py` (in this repo, reusable —
not a one-off):
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\plot_training_curve.py wakeword_training\output\yuuka_wakeword_v1
```
Pass either the metrics JSON file directly or the model's output directory (it'll find the
`*_metrics.json` inside). Produces a two-panel accuracy + recall chart, saved next to the
metrics file as `<model_name>_training_curve.png`.

## Testing the model

**`eval`** (above) is the built-in quantitative test — run it, read FPPH/recall, look at the
DET curve PNG.

**Live mic test** — `wakeword_training/test_mic.py` loads the exported `.onnx` and prints a
live confidence meter as you speak, using `WakeWordModel` from the library's inference API
(`livekit.wakeword.WakeWordModel` — stateless, `.predict(audio_chunk)` returns `{model_name:
score}` for a ~2-second 16kHz chunk):
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py
```
**Note on live-inference CPU cost**: naive continuous prediction (recomputing the full
2-second window on every new 80ms audio frame — what both `test_mic.py` and the library's own
`WakeWordListener` reference implementation do) pins all CPU cores: ~25x redundant
recomputation (96% window overlap between consecutive predictions) plus `onnxruntime`
parallelizing every tiny inference call across all cores by default. Not a bug — just not
optimized for continuous polling. **Doesn't apply to the actual bot integration**, which calls
the detector once per already-closed segment (see below), not continuously per-frame.

## Gotchas hit along the way

- Console crashes without `PYTHONUTF8=1` (Windows codepage vs. `rich`'s unicode output).
- `uv pip install`/`uv tool install` resolves CPU-only `torch` by default even with a GPU
  present — a **per-environment** default, needs the `--torch-backend=auto` fix applied to
  *every* venv/tool install independently, not just once globally.
- Console/log text renders as mojibake (e.g. `Γûê` instead of `█`) without `chcp 65001` first —
  cosmetic (the underlying data is correct UTF-8), but persists into any log file the console
  output gets piped to.
- A non-raw Python docstring containing a Windows path like `...\uv\tools\...` breaks with
  `SyntaxError: (unicode error) 'unicodeescape' codec... \uXXXX escape` — `\u` gets parsed as a
  unicode escape. Use a raw string (`r"""..."""`) for any docstring/string with literal Windows
  paths.
- Feature extraction is CPU-only by design in the base library (hardcoded
  `CPUExecutionProvider`) — PR #71 makes this configurable, but `onnxruntime-gpu` still doesn't
  actually reach CUDA in this environment (missing DLL, see above); CPU + multiprocessing is
  fast enough regardless.
- PR #71's branch predates a Windows fix that later landed on `main` (`webrtcvad` →
  `webrtcvad-wheels`) — installing the PR pulls the broken old dependency back in. Must be
  manually re-fixed in any environment built from this PR (see Setup above).
- Parallel `augment` + a single background file = severe I/O contention, not a code bug — see
  the chunking section above.
- `augment` is not resumable (deletes all `_rN.wav` files every invocation); `generate` and
  `train` are.
- PowerShell + native commands: `$ErrorActionPreference = "Stop"` combined with `2>&1` makes
  PowerShell 5.1 treat *any* stderr line from a native process (even a harmless warning) as a
  terminating error, killing an otherwise-successful run. Use `"Continue"` and check
  `$LASTEXITCODE` explicitly instead (see `run_v1_overnight.ps1`).

## Current status

**v1** (`yuuka_wakeword_v1`, 30,000 augmented positive clips, 60,000 training steps): real
signal, not production-ready. At the default threshold (0.5): FPPH ~0.05-0.35 (near the
config's `target_fp_per_hour: 0.1` target) but only ~53% recall. At the trainer's own
"optimal" threshold (0.02): 88% recall but FPPH=44 (44 false triggers/hour — unusable as a
sole trigger, though tolerable as a pre-filter gate, see below). No single threshold yet gives
both low false-accepts and reliable detection — the model needs more data/steps to sharpen
that separation. Validation accuracy climbed from chance (~50%) to ~76%, confirming the
pipeline and training loop both work correctly; v1 is a real improvement over the POC run
below, just not yet good enough to promote.

**POC** (`yuuka_wakeword`, 367 positive clips, 3,600 steps, deliberately starved to validate
the pipeline before spending GPU-hours): FPPH=91 at 80% recall — essentially noise. This is
still the model currently promoted to `models/wake_word/yuuka_wakeword.onnx` and live in the
bot (see below) — acceptable there specifically because it's a pre-filter, not the sole
trigger (a false accept just wastes one STT call).

## Next steps

1. **Improve v1's data/scale for a v2 run**, in rough order of expected impact:
   - More positive/negative data (v1 used 10,000/10,000; library class default is 25,000)
   - More `background_noise` training samples (v1 used only 200/40 — tiny next to 30,000
     positive/negative; likely under-representing "normal room audio" as a class)
   - More training steps (v1 used 50,000; library default is even higher)
   Use a **new `model_name`** (e.g. `yuuka_wakeword_v2`) so v1's output isn't overwritten.
2. Re-run `generate → augment → train → export → eval` with the new config/model_name — the
   consolidated venv above is fast enough now that this is a practical iteration loop, not an
   overnight-only commitment.
3. Check `eval`'s FPPH against `target_fp_per_hour: 0.1` *and* recall at that threshold before
   considering a model good enough to promote — a model is only actually better than what's
   live if it improves the FPPH/recall tradeoff at some usable threshold, not just accuracy.

### Promoting a model to run

The bot does *not* load straight out of `wakeword_training/output/` — that directory is
gitignored and gets regenerated/overwritten by the training pipeline, so a fresh clone or a
production deploy has no way to get the file `utils/wake_acoustic.py` needs.
`models/wake_word/` is a small, git-tracked home for promoted models, kept separate from the
training scaffold. Each promoted version keeps its training run's `model_name` as its filename
(`yuuka_wakeword.onnx` for the POC currently live, `yuuka_wakeword_v1.onnx` for v1, and so on)
rather than overwriting one fixed name — every version stays available, and rolling back is
just pointing at an older filename, not a git revert:
```powershell
cp wakeword_training/output/<model_name>/<model_name>.onnx models/wake_word/<model_name>.onnx
```
Then point `Config.stt_wake_acoustic_model_path` at the new file and set
`Config.stt_wake_acoustic_threshold` to whatever threshold `eval` showed as the right operating
point for that model (not necessarily its "optimal_threshold" — see v1's results above, where
that pick trades away FPPH for recall) — either bump the defaults in `bot/config.py` (commit it
alongside the new model file so the repo's default always means "the current best version"), or
set `STT_WAKE_ACOUSTIC_MODEL_PATH`/`STT_WAKE_ACOUSTIC_THRESHOLD` in `.env` for a
per-deployment override without touching code.

**v1 is trained but not yet promoted** — its FPPH/recall tradeoff isn't clearly better than the
POC's at any single threshold (see Current status above), so this is a judgment call, not
automatic. Promoting it now would mean picking a threshold and accepting its specific tradeoff;
waiting for a v2 run is the other option.
