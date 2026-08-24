# wakeword_training

Trains the acoustic wake-word model ("Yuuka") that gates STT in `/ai voice` — see
`utils/wake_acoustic.py` for how the bot actually uses a trained model.

**Currently live:** `yuuka_wakeword_v2` at threshold `0.02` — catches ~87% of real "Yuuka"s. It's
a pre-filter, not the trigger: it only decides whether an utterance is worth transcribing, and
the text match in `utils/wake.py` makes the final call. So a false alarm just wastes one
transcription, while a miss silently drops a real summon.

**This file is a quick-start guide.** For the full reference — why this approach, how each step
works, every gotcha, and the model-quality numbers — see **[TRAINING.md](TRAINING.md)**.

## What's in this directory

| Path | What it is |
|---|---|
| `setup_env.ps1` | Run once — builds the training environment (see Setup below) |
| `configs/*.yaml` | Training run configs — what to train, how much data, how many steps |
| `run_v2_overnight.ps1` | **The runner.** Runs the full pipeline (`setup → generate → augment → train → export → eval`) unattended, with logging, and stops on the first failure |
| `run_v1_overnight.ps1` | The same, for the older v1 config — kept for reference |
| `compare_models.py` | Ranks two or more trained models against each other — **the tool that decides whether a new model is actually better** |
| `test_mic.py` | Live microphone test for a trained model |
| `plot_training_curve.py` | Turns a training run's metrics into an accuracy/recall chart |
| `.venv/` | The training environment (gitignored — not in the repo, you build it) |
| `data/` | Downloaded/generated training data (gitignored — large, regenerable) |
| `output/` | Trained models per run (gitignored — see "Using a trained model" below) |
| `logs/` | Logs from unattended runs (gitignored) |

## Setup (one time)

```powershell
powershell -File wakeword_training\setup_env.ps1
```

Builds `wakeword_training/.venv` with everything needed (GPU-accelerated generation,
multi-core-accelerated augmentation/feature-extraction — TRAINING.md explains why it needs a
patched install). Stops with a clear error on the first thing that fails; won't leave you with a
silently-broken half-working environment.

**One thing it can't automate**: a real background-noise recording is used to make training data
sound less synthetic. It's gitignored, so a fresh clone won't have it. The setup script prints
exactly what to do about this when it finishes — copy one over or record a fresh one, then run
the single command it gives you to prepare it.

## Running a training pipeline

The easy way — one command, runs the whole chain unattended and logs to `logs/`:

```powershell
powershell -File wakeword_training\run_v2_overnight.ps1
```

It handles the fiddly parts for you (sets `PYTHONUTF8`, moves to the repo root, uses the right
config argument style per stage) and stops immediately if a stage fails instead of feeding broken
output into the next one. To keep it running after you close the terminal:

```powershell
Start-Process powershell -WindowStyle Hidden -ArgumentList `
    "-NoProfile","-ExecutionPolicy","Bypass","-File","wakeword_training\run_v2_overnight.ps1"
```

The machine has to stay awake — the script doesn't manage power settings, and it won't survive a
log-off or reboot (use Task Scheduler if you need that).

**Expect it to take about a day.** `generate` is ~95% of the wall time (19h20m on the v2 run);
everything after it finishes in about 75 minutes combined. It's resumable — re-running the script
picks up where it left off rather than starting over, so spreading it across nights is fine.

<details>
<summary>Running the stages by hand instead</summary>

From the **repo root** (not `wakeword_training/` — the configs use repo-root-relative paths):

```powershell
$env:PYTHONUTF8="1"
$py = "wakeword_training\.venv\Scripts\python.exe"
$cfg = "wakeword_training/configs/yuuka_v2.yaml"

& $py -m livekit.wakeword setup    --config $cfg
& $py -m livekit.wakeword generate $cfg
& $py -m livekit.wakeword augment  $cfg
& $py -m livekit.wakeword train    $cfg
& $py -m livekit.wakeword export   $cfg
& $py -m livekit.wakeword eval     $cfg
```

Note `setup` takes `--config` while every other stage takes the path positionally.
</details>

### Starting a new run

Copy `configs/yuuka_v2.yaml` to a new file, change `model_name` to something new (e.g.
`yuuka_wakeword_v3`), and adjust what you want to change — see TRAINING.md's "The config file"
for what each field does. Then copy `run_v2_overnight.ps1` and point its `$config` at your new
file.

Always use a new `model_name`. Runs sharing a name overwrite each other's output.

## Checking results

**Is the new model actually better?** This is the one that matters, and a single model's own
`eval.json` can't answer it — compare directly:

```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\compare_models.py --models yuuka_wakeword_v2 <your_new_run>
```

It prints recall for each model at matched false-alarm budgets, so you're comparing like with
like. **A new model is only better if it wins a row.** Read the higher-budget rows — this model
is a pre-filter, so missing a real summon costs you more than an occasional false alarm.

Ignore `eval.json`'s headline recall/FPPH and its `aut` score when ranking models; both can make
a worse model look better. TRAINING.md's "Evaluating and comparing models" explains why.

**Training-progress chart**:
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\plot_training_curve.py wakeword_training\output\<model_name>
```

**Hands-on test** — talk to the model through your microphone and watch the confidence meter:
```powershell
wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py
```
It tests the currently-promoted model; edit `MODEL_PATH` at the top to point somewhere else.

## Using a trained model in the bot

A model in `output/` isn't visible to the bot at all — that folder is gitignored and gets rebuilt
by the pipeline. You have to copy it into `models/wake_word/` and point the config at it:

```powershell
cp wakeword_training/output/<model_name>/<model_name>.onnx models/wake_word/<model_name>.onnx
```

Then update **both** `stt_wake_acoustic_model_path` and `stt_wake_acoustic_threshold` in
`bot/config.py`, and `git add` the `.onnx`. The threshold has to be re-derived per model —
the same number means something different on a different model.

Full walkthrough, including the `.env` trap that silently disables the gate: TRAINING.md's
"Promoting a model".
