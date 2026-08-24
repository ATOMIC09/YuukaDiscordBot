<#
.SYNOPSIS
    Runs the yuuka_wakeword_v2 pipeline unattended: setup -> generate -> augment ->
    train -> export -> eval.

.DESCRIPTION
    v2 scales up over v1 (see configs/yuuka_v2.yaml's header comment): n_samples
    10000->25000, n_background_samples 200->2000, steps 50000->100000. Per
    TRAINING.md's measured time-budget table, `generate` alone is ~11h for
    25,000 positive clips on an RTX 3070, and negatives/val/backgrounds add
    more on top -- this config realistically spans several nights, not one.
    `generate` is resumable either way (it counts existing clip_NNNNNN.wav
    files and picks up where it left off), so re-running this script on
    subsequent nights continues rather than restarting. `train` checkpoints
    periodically within each phase too.

    Note this repo's training venv (wakeword_training/.venv) is gitignored
    and machine-local -- if it isn't built yet on this machine, run
    setup_env.ps1 first (this script does not build it for you).

    Stops immediately if any stage exits non-zero, rather than plowing into
    the next stage on broken output.

.EXAMPLE
    To run in the current window (stays alive only as long as this window does):
        powershell -File wakeword_training\run_v2_overnight.ps1

    To run detached, so closing this terminal doesn't kill it:
        Start-Process powershell -WindowStyle Hidden -ArgumentList `
            "-NoProfile","-ExecutionPolicy","Bypass","-File","wakeword_training\run_v2_overnight.ps1"

    Either way, the machine must stay powered on and not sleep for this to keep
    running overnight -- this script does NOT manage power settings itself
    (deliberately; the machine already has sleep disabled at the system level).
    It does not survive a log-off or reboot; use Task Scheduler ("Run whether
    user is logged on or not") if you need that.
#>

# Deliberately NOT "Stop": livekit-wakeword writes harmless warnings (e.g. the
# missing-HF_TOKEN notice) to stderr, and PowerShell 5.1 wraps every stderr
# line from a native command as a terminating NativeCommandError when 2>&1 is
# used -- with "Stop" set, that kills the whole run on a mere warning even
# though the process itself continues/succeeds. The explicit $LASTEXITCODE
# check below is the real failure detector; this preference only needs to not
# fight it.
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"

# Repo root, regardless of where this script was invoked from.
Set-Location (Split-Path $PSScriptRoot -Parent)

$config = "wakeword_training/configs/yuuka_v2.yaml"
$logDir = "wakeword_training/logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "yuuka_wakeword_v2_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# The consolidated project-local venv (wakeword_training/.venv), not the
# global `livekit-wakeword` tool install -- this one has CUDA torch,
# webrtcvad-wheels, and PR #71's multiprocessing augment/feature-extraction
# fixes all verified working together. Invoked via `python -m` so it never
# touches any shared PATH/shim.
$py = "wakeword_training\.venv\Scripts\python.exe"

$stages = @("setup", "generate", "augment", "train", "export", "eval")

Add-Content -Path $log -Value "===== $(Get-Date -Format 'u')  starting yuuka_wakeword_v2 run ====="

foreach ($stage in $stages) {
    $line = "===== $(Get-Date -Format 'u')  $stage ====="
    Add-Content -Path $log -Value $line
    Write-Host $line

    # `setup` takes the config path via --config; every other stage takes it
    # as a positional argument. Not interchangeable.
    if ($stage -eq "setup") {
        & $py -m livekit.wakeword setup --config $config 2>&1 | Tee-Object -Append -FilePath $log
    } else {
        & $py -m livekit.wakeword $stage $config 2>&1 | Tee-Object -Append -FilePath $log
    }

    if ($LASTEXITCODE -ne 0) {
        $failLine = "===== $(Get-Date -Format 'u')  $stage FAILED (exit $LASTEXITCODE), stopping ====="
        Add-Content -Path $log -Value $failLine
        Write-Host $failLine
        exit $LASTEXITCODE
    }
}

$doneLine = "===== $(Get-Date -Format 'u')  all stages complete ====="
Add-Content -Path $log -Value $doneLine
Write-Host $doneLine
Write-Host "Model: wakeword_training/output/yuuka_wakeword_v2/yuuka_wakeword_v2.onnx"
Write-Host "Eval:  wakeword_training/output/yuuka_wakeword_v2/yuuka_wakeword_v2_eval.json"
