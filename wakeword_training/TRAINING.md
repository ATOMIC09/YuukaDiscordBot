# Training Yuuka's acoustic wake-word model

## Goal

Replace (or gate ahead of) the current text-based wake-word matcher (`utils/wake.py`) with an
acoustic model that listens to raw audio and decides whether "Yuuka" was said, **before**
paying for a full STT call. Today, every utterance spoken in a voice channel gets fully
transcribed (local `faster-whisper` or the Groq API) via `utils/stt.py`, then `utils/wake.py`
fuzzy-matches the transcript — expensive and wasteful, since most utterances aren't addressed
to the bot at all. A cheap always-on acoustic classifier can gate that: only call STT after
the classifier fires.

**This document covers training only.** No bot integration has been done — see "Next steps"
at the bottom for that.

## Why livekit-wakeword, not openWakeWord

openWakeWord was tried first and had "a lot of problems on Windows" — its frozen
feature-extractor models ship as **TFLite**, which has poor/no Windows wheel support, plus a
`webrtcvad` dependency needing an MSVC compiler.

[livekit/livekit-wakeword](https://github.com/livekit/livekit-wakeword) fixes this directly:
same underlying approach (frozen mel-spectrogram + Google `speech_embedding` feature
extractors, openWakeWord's own pretrained models) but re-exported as **ONNX** instead of
TFLite, a Conv-Attention classifier head instead of a flat DNN, and a merged PR specifically
fixing Windows installation (`webrtcvad` → `webrtcvad-wheels`, fixed espeak UTF-8 decoding).
Deploy-time footprint is just `numpy` + `onnxruntime`.

Confirmed working on this Windows machine — see "Verified working" below.

## One name, multiple accents, not multiple words

"Yuuka" is one wake word. The `target_phrases` list has multiple *script spellings*
(`yuuka`, `yuka`, `ゆうか`, `ユーカ`, `ยูกะ`, `ยูคะ`) because Thai/Japanese TTS needs native
script to phonemize correctly — not because these are different words. Accent diversity
(a Thai speaker's English pronunciation vs. a native English speaker's) is handled instead by
`voxcpm_tts.voice_design_prompts` — natural-language persona descriptions VoxCPM2 uses to vary
the voice, including explicit non-native-accent prompts. This mirrors what the original
hand-built `wake_multilang/` dataset did by using dozens of different-locale Edge-TTS voices
to read the same phrase.

## Prerequisites

- `uv` (already used by this repo)
- Windows: set `PYTHONUTF8=1` before every `livekit-wakeword` command — the CLI's `rich`-based
  console output crashes on Windows' legacy codepage otherwise (a `→` character in help text,
  or similar, throws `UnicodeEncodeError`).
- Optional but strongly recommended: an NVIDIA GPU. `generate` calls a full neural TTS model
  (VoxCPM2) per clip — **~20-30s/clip on CPU vs ~1.6s/clip on GPU** (RTX 3070 tested). CPU-only
  generation for a real-sized dataset (thousands of clips) is impractical (17+ hours).
- Disk space: the `setup` step downloads ~22GB (VoxCPM2 weights ~5GB + ACAV100M generic-negative
  feature bank ~17GB + RIRs). Point `data_dir`/`output_dir` at a drive with room — see config below.

## Installation

```powershell
uv tool install "livekit-wakeword[train,eval,export,voxcpm]"
```

**Don't forget `voxcpm`** — installing without it (`[train,eval,export]` alone) installs fine
but fails at `generate` time with `ImportError: VoxCPM is not installed`.

### GPU: torch installs CPU-only by default, needs a manual swap

`uv tool install` resolves the plain CPU build of `torch`/`torchaudio` even when a CUDA GPU is
present. Check:
```powershell
& "$env:APPDATA\uv\tools\livekit-wakeword\Scripts\python.exe" -c "import torch; print(torch.cuda.is_available())"
```
If `False` but you have an NVIDIA GPU, force the CUDA build into the same tool environment:
```powershell
uv pip install --python "$env:APPDATA\uv\tools\livekit-wakeword\Scripts\python.exe" --torch-backend=auto --reinstall-package torch --reinstall-package torchaudio torch torchaudio
```
`--torch-backend=auto` auto-detects the right CUDA tag for your driver. Verify again after —
should print `True` and your GPU name.

Note: the frozen mel-spectrogram/speech-embedding feature extractors (used in `augment` and at
inference time) are hardcoded to `CPUExecutionProvider` in the library's source regardless of
what's installed — only VoxCPM2's `generate` step benefits from GPU. This is by design (those
models are tiny; CPU is fast enough for them) and isn't worth fighting.

### For live mic testing (optional)
```powershell
uv pip install --python "$env:APPDATA\uv\tools\livekit-wakeword\Scripts\python.exe" "livekit-wakeword[listener]"
```
Adds `pyaudio` for microphone capture — see `test_mic.py` below.

## Folder layout

- **Config lives in the repo**: `wakeword_training/configs/yuuka.yaml` (tiny text file, tracked
  in git as reference — though the large generated data below is gitignored).
- **Heavy data lives in `wakeword_training/data/` and `wakeword_training/output/`**, set via
  the config's `data_dir`/`output_dir` fields as **absolute paths** — a relative path like
  `./data` would resolve against whatever directory the CLI happens to be invoked from
  (repo root vs. inside `wakeword_training/`), which varies, so don't use relative paths here.
  Both folders are gitignored (large binary data has no business in version control). If disk
  space is ever tight again, these can point at another drive instead — `data_dir` holds the
  ~22GB shared `setup` downloads (VoxCPM weights, ACAV100M, RIRs) — **shared across every
  experiment, never duplicated**. `output_dir` holds the per-experiment stuff.
- **Per-experiment folder is `output_dir / model_name`** (see `config.py`: `model_output_dir
  = Path(output_dir) / model_name`). Every split's clips, extracted `.npy` features, the
  trained `.pt`/`.onnx`, metrics JSON, and DET curve PNG all live there.
  **Give each meaningfully different experiment its own `model_name`** (e.g.
  `yuuka_wakeword_poc`, `yuuka_wakeword_v1`) so runs don't overwrite each other. Reusing the
  same `model_name` across runs is how you *intentionally* resume/top-up a dataset (see below)
  — the shared `data_dir` downloads are never affected either way.

## The config file

See `wakeword_training/configs/yuuka.yaml` for the full file. Key fields:

- `target_phrases` — script spellings of "Yuuka" (see accent note above)
- `tts_backend: voxcpm` — required for Thai/Japanese (Piper is English-only, single locale)
- `voice_design_prompts` — accent/persona diversity (see accent note above)
- `custom_negative_phrases` — hand-curated Thai confusable words/phrases (ยูนะ, ยูริ, ยูกิ,
  ยูทูบ, command-like phrases, etc.), sourced from an earlier abandoned openWakeWord attempt's
  `wake_chirp3_th.zip/metadata.csv` (negative-labeled rows' `canonical_text`, deduplicated) —
  reusing that curation effort as text even though the pre-rendered WAV files aren't used
- `n_samples` / `n_samples_val` / `n_background_samples(_val)` — how many clips to generate
  per split. **Currently set low (300/60/100/20) for a proof-of-concept run** — the library's
  own shipped example config defaults to 25000/5000. Scale up for real quality (see below).
- `steps` — training steps for phase 1; actual total is `steps + steps/10 + steps/10` (3
  phases). **Currently 3000** (→ ~3600 total) for the same proof-of-concept reason; shipped
  default is 100000.
- `augmentation.background_paths` — point at real captured audio for realistic noise. This
  project converted `vc_negative_audio.opus` (78 min of real Discord voice-channel audio) to
  16kHz mono WAV and dropped it here — genuinely valuable, since it's real deployment-condition
  noise the TTS pipeline can't synthesize itself.
- `batch_n_per_class` — per-training-step batch composition; `ACAV100M_sample: 1024` dominates
  (draws from the large pre-downloaded generic-negative bank), `positive`/`adversarial_negative`/
  `background_noise: 50` each draw from your own generated data.

## Pipeline

Run each step from the repo root, with `PYTHONUTF8=1` set:

```powershell
$env:PYTHONUTF8="1"

livekit-wakeword setup   wakeword_training/configs/yuuka.yaml   # one-time, ~22GB download
livekit-wakeword generate wakeword_training/configs/yuuka.yaml  # synthesize clips (VoxCPM2)
livekit-wakeword augment  wakeword_training/configs/yuuka.yaml  # noise/reverb + feature extraction
livekit-wakeword train    wakeword_training/configs/yuuka.yaml  # train the classifier
livekit-wakeword export   wakeword_training/configs/yuuka.yaml  # .pt -> .onnx
livekit-wakeword eval     wakeword_training/configs/yuuka.yaml  # DET curve, FPPH, recall
```

(`livekit-wakeword run <config>` chains generate→augment→train→export, but running stage-by-stage
is worth it, at least the first time, to catch problems early — see gotchas below.)

### `setup`
Downloads VoxCPM2 weights, the ACAV100M generic-negative feature bank (~17GB), RIRs, and picks
up anything already in `augmentation.background_paths`. One-time per `data_dir`; safe to rerun
(skips what's already there).

### `generate`
The step most likely to need attention. For each clip index it deterministically cycles
through `target_phrases` (`index % len(phrases)`) and, independently, through every
`(voice_design_prompt, cfg_value, inference_timesteps)` combination (`itertools.product`
order) — **not random selection**. The only randomness is VoxCPM2's own generation noise, so
identical parameter combos still produce different-sounding clips each time. `n_samples` just
sets how many times this loop runs before stopping.

**Resumable**: counts existing `clip_NNNNNN.wav` files in each split folder before starting,
and continues/skips accordingly. Safe to kill and rerun — nothing is lost, and lowering
`n_samples` after a partial run just means it may already be "done" (skips straight past).

Time budget (GPU, ~1.6s/clip observed on an RTX 3070; ~20-30s/clip on CPU):
| `n_samples` | ~generate time (positives only) |
|---|---|
| 300 (poc) | ~10 min |
| 4,000 | ~1.8 hours |
| 10,000 | ~4.5 hours |
| 25,000 (library default) | ~11 hours |
Negatives/val/backgrounds add proportionally more.

### `augment`
Applies noise/reverb augmentation, then extracts features through the frozen ONNX
mel-spectrogram + speech-embedding models (openWakeWord's own pretrained models, re-exported).
Runs on CPU by design (see GPU note above) — still fast (~2-3 min for a small dataset) since
these are tiny models. Saves `*_features_{train,test}.npy` files, shape `(N, 16, 96)`.

### `train`
3-phase adaptive training (phase 1 = `steps`, phase 2/3 = `steps/10` each). Checkpointing and
validation are **proportional to `steps`**, not an absolute step count (`validation_interval =
steps // 20`, checkpoints only save in each phase's last quarter) — lowering `steps` doesn't
risk "zero checkpoints saved." Saves `{model_name}.pt` and `{model_name}_metrics.json` (a
JSON array of validation snapshots — step/phase/fpph/recall/accuracy — useful for plotting a
training-progress chart, since there's no built-in one; see "Charting" below).

### `export`
Converts the `.pt` to `.onnx` (with a torch/onnxruntime parity check baked into the
`torch.onnx.export` pipeline). Fast, no GPU needed.

### `eval`
Runs the exported `.onnx` against the held-out test set + the large ACAV100M validation pool,
computes AUT/FPPH/recall, and saves **`{model_name}_det.png`** — a DET curve (False Positive
Rate vs. False Negative Rate across thresholds) with metrics annotated. This is the one
built-in chart. Also saves `{model_name}_eval.json`.

## Charting training progress

No built-in "loss/accuracy over time" plot, but the data exists in `{model_name}_metrics.json`
(written by `train`). Minimal script to plot validation accuracy per phase:

```python
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open(r"<output_dir>/<model_name>/<model_name>_metrics.json") as f:
    data = json.load(f)
rows = [d for d in data if d["phase"] in (1, 2, 3)]  # exclude final summary rows

fig, ax = plt.subplots(figsize=(9, 5.5))
colors = {1: "#2563eb", 2: "#d97706", 3: "#16a34a"}
for p in (1, 2, 3):
    xs = [d["elapsed_s"] for d in rows if d["phase"] == p]
    ys = [d["accuracy"] for d in rows if d["phase"] == p]
    ax.plot(xs, ys, "o-", color=colors[p], label=f"Phase {p}")
ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="Chance (50%)")
ax.set_xlabel("Elapsed training time (s)"); ax.set_ylabel("Validation accuracy")
ax.legend(); ax.grid(True, alpha=0.3)
fig.savefig("training_curve.png", dpi=150)
```
Run with the tool's own Python (has matplotlib via the `eval` extra).

## Testing the model

**`eval`** (above) is the built-in quantitative test — run it, read FPPH/recall, look at the
DET curve PNG.

**Live mic test** — `wakeword_training/test_mic.py` (in this repo) loads the exported `.onnx`
and prints a live confidence meter as you speak, using `WakeWordModel` from the library's
inference API (`livekit.wakeword.WakeWordModel` — stateless, `.predict(audio_chunk)` returns
`{model_name: score}` for a ~2-second 16kHz chunk). Run with the tool's Python (needs the
`listener` extra installed for `pyaudio`):
```powershell
& "$env:APPDATA\uv\tools\livekit-wakeword\Scripts\python.exe" wakeword_training\test_mic.py
```
**Note on live-inference CPU cost**: naive continuous prediction (recomputing the full
2-second window on every new 80ms audio frame — which is what both `test_mic.py` and the
library's own `WakeWordListener` reference implementation do) pins all CPU cores, because
(a) it's ~25x redundant recomputation (96% window overlap between consecutive predictions),
and (b) `onnxruntime` parallelizes every tiny inference call across all cores by default. Not
a sign anything is broken — just not optimized for continuous deployment. Fixes for real
integration: cap `onnxruntime` `SessionOptions.intra_op_num_threads` to 1 (these models are
too small to benefit from multi-threading), and/or predict less often than every single frame.

## Gotchas hit during this session

- Console crashes without `PYTHONUTF8=1` (Windows codepage vs. `rich`'s unicode output).
- `uv tool install` without the `voxcpm` extra installs fine but fails at `generate` time.
- `uv tool install` resolves CPU-only `torch` even with a GPU present — needs the manual
  `--torch-backend=auto --reinstall-package` swap (see above).
- A non-raw Python docstring containing a Windows path like `...\uv\tools\...` breaks with
  `SyntaxError: (unicode error) 'unicodeescape' codec can't decode... \uXXXX escape` — `\u`
  gets parsed as a unicode escape. Use a raw string (`r"""..."""`) for any docstring/string
  containing literal Windows paths.
- Feature extraction (`augment`) is CPU-only by design (hardcoded `CPUExecutionProvider` in
  the library source) — don't expect GPU to help there, only `generate` benefits.

## Current status (as of this proof-of-concept run)

Ran the full pipeline end-to-end successfully — **the plumbing works**, including
Thai/Japanese/English VoxCPM2 synthesis. Model quality is **not usable yet**, by design: this
run deliberately used a fraction of the recommended data (367 positive clips vs. the library's
tested 25,000) and steps (3,600 vs. 120,000) purely to validate the pipeline before spending
GPU-hours on a real run.

Result: `Optimal threshold: 0.02 (FPPH=91.06, Recall=0.800)` — ~91 false triggers/hour at 80%
recall, far above the config's `target_fp_per_hour: 0.1` target. Validation accuracy stayed
flat around 50% (chance level) throughout training. Expected outcome for this data/step count,
not a sign of a broken pipeline.

## Next steps

1. **Scale up for a real run.** Bump `n_samples`/`n_samples_val`/`n_background_samples(_val)`
   and `steps` back toward the library's tested defaults (25000/5000/100000 steps), under a
   **new `model_name`** (e.g. `yuuka_wakeword_v1`) so this proof-of-concept run isn't
   overwritten. Budget GPU time accordingly (see the `generate` time table above).
2. Re-run `generate → augment → train → export → eval` with the new config/model_name.
3. Check `eval`'s FPPH against the `target_fp_per_hour: 0.1` target and per-phrase recall
   before considering the model usable.
4. **Bot integration is not done and not covered here.** When ready: the acoustic detector
   should run ahead of `voice_hub.subscribe`'s segment callback in `cogs/ai/voice_chat.py`,
   consuming the same 16kHz mono audio `utils/audio.py:pcm_to_mono16k()` already produces for
   Whisper. Recommend keeping `utils/wake.py`'s text matcher as a confirmation layer after an
   acoustic trigger (rather than fully replacing it), since an acoustic false-accept would
   otherwise go straight to the LLM. Remember the live-inference CPU fixes noted above
   (thread-capped ONNX sessions, sensible poll interval) before deploying this continuously.
5. Add `.gitignore` coverage was already done for the raw source assets at repo root — verify
   nothing under `wakeword_training/data/` or `wakeword_training/output/` (if ever pointed
   back at a path inside the repo) gets accidentally committed.
