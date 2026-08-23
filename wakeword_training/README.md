# wakeword_training

Trains the acoustic wake-word model ("Yuuka") that gates STT in `/ai voice` — see
`utils/wake_acoustic.py` for how the bot actually uses a trained model.

**This file is a quick-start guide.** For the full technical reference — why this approach was
chosen over alternatives, exactly how each pipeline step works, every gotcha hit along the way,
and current model-quality results — see **[TRAINING.md](TRAINING.md)**.

## What's in this directory

| Path | What it is |
|---|---|
| `setup_env.ps1` | Run once — builds the training environment (see Setup below) |
| `configs/*.yaml` | Training run configs — what to train, how much data, how many steps |
| `run_v1_overnight.ps1` | Runs the full pipeline (`setup → generate → augment → train → export → eval`) unattended, with logging |
| `test_mic.py` | Live microphone test for a trained model |
| `plot_training_curve.py` | Turns a training run's metrics into an accuracy/recall chart |
| `.venv/` | The training environment (gitignored — not in the repo, you build it) |
| `data/` | Downloaded/generated training data (gitignored — large, regenerable) |
| `output/` | Trained models per run (gitignored — see "Promoting a model" in TRAINING.md to make one usable by the bot) |
| `logs/` | Logs from unattended runs (gitignored) |

## Setup (one time)

```powershell
powershell -File wakeword_training\setup_env.ps1
```

Builds `wakeword_training/.venv` with everything needed (GPU-accelerated generation,
multi-core-accelerated augmentation/feature-extraction — see TRAINING.md for what that means and
why it needs a patched install). Stops with a clear error on the first thing that fails; won't
leave you with a silently-broken half-working environment.

**One thing it can't automate**: a real background-noise recording is used to make training data
sound less synthetic. It's gitignored (not something that belongs in git), so a fresh clone
won't have it. The setup script prints exactly what to do about this once it finishes — either
copy one over from wherever you have one, or record a fresh one, then run the one command it
gives you to prepare it for training.

## Running a training pipeline

Everything below assumes your terminal's current directory is the **repo root** (not
`wakeword_training/` itself — the configs use paths relative to repo root).

```powershell
$env:PYTHONUTF8="1"
$py = "wakeword_training\.venv\Scripts\python.exe"

& $py -m livekit.wakeword setup    --config wakeword_training/configs/yuuka_v1.yaml
& $py -m livekit.wakeword generate wakeword_training/configs/yuuka_v1.yaml
& $py -m livekit.wakeword augment  wakeword_training/configs/yuuka_v1.yaml
& $py -m livekit.wakeword train    wakeword_training/configs/yuuka_v1.yaml
& $py -m livekit.wakeword export   wakeword_training/configs/yuuka_v1.yaml
& $py -m livekit.wakeword eval     wakeword_training/configs/yuuka_v1.yaml
```

Or, to run the whole thing unattended (useful since `generate` in particular can take hours):
```powershell
powershell -File wakeword_training\run_v1_overnight.ps1
```

To start a **new** training run instead of continuing/reusing an existing one: copy
`configs/yuuka_v1.yaml` to a new file, change `model_name` to something new (e.g.
`yuuka_wakeword_v2`), and adjust whatever you want to change about the run (amount of data,
training steps, etc. — see TRAINING.md's "The config file" section for what each field does).
Point the commands above at your new config instead.

## Checking results

**Quantitative** — after `eval` runs, look at `wakeword_training/output/<model_name>/
<model_name>_eval.json` and the DET curve PNG next to it (`<model_name>_det.png`). The numbers
that matter: false-positives-per-hour (lower is better) and recall (higher is better) — see
TRAINING.md's "Current status" section for what "good enough" looks like and why that's not a
single obvious number.

**Training-progress chart**:
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\plot_training_curve.py wakeword_training\output\<model_name>
```

**Hands-on test** — talk to the model directly via your microphone:
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py
```
(Edit `MODEL_PATH` near the top of `test_mic.py` first if you want to test a model other than
the one it currently points at.)

## Using a trained model in the bot

Not covered here — see TRAINING.md's "Promoting a model to run" section. Short version: a
trained model in `wakeword_training/output/` isn't visible to the bot until you copy it into
`models/wake_word/` and point `Config.stt_wake_acoustic_model_path` at it.
