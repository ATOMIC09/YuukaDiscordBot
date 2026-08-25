<#
.SYNOPSIS
    One-time environment setup for wake-word training on a fresh Windows PC.

.DESCRIPTION
    Builds wakeword_training/.venv from scratch: PR #71's multiprocessing/GPU-config
    branch of livekit-wakeword. torch is resolved straight to a CUDA build on the
    initial install (--torch-backend=auto works there directly, verified -- no
    separate swap needed). webrtcvad does need a separate fix: PR71 predates a
    later Windows compat fix on main (webrtcvad -> webrtcvad-wheels), and verified
    that listing webrtcvad-wheels alongside the initial install doesn't work
    reliably (uv installs both, since they're different package names providing
    the same import path, and whichever lands last wins non-deterministically) --
    an explicit uninstall-then-install is the only reliable fix. Then verifies
    everything independently. The tracked configs (yuuka.yaml,
    yuuka_v1.yaml) already use repo-root-relative paths (./wakeword_training/...),
    not machine-specific absolute ones, so nothing needs rewriting after a clone --
    this script's only remaining job is building the venv correctly.

    One thing this script cannot automate: the real background-noise recording
    (background_noise_source.opus) is gitignored and never leaves the original
    machine via git -- copy it over, or record a fresh one, then run the
    chunking command this script prints at the end.

.EXAMPLE
    powershell -File wakeword_training\setup_env.ps1
#>

$ErrorActionPreference = "Continue"

$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot
Write-Host "Repo root: $repoRoot"

$venvPy = "wakeword_training\.venv\Scripts\python.exe"

# --- 1. Create the venv -------------------------------------------------
Write-Host "`n=== Creating venv ==="
uv venv wakeword_training/.venv --python 3.12
if (-not (Test-Path $venvPy)) {
    Write-Host "FATAL: venv creation failed, $venvPy not found."
    exit 1
}

# --- 2. Install PR71 with all extras, torch resolved to CUDA from the --
#        start (--torch-backend=auto works on the initial install, verified
#        -- no separate reinstall/swap needed for torch specifically).
Write-Host "`n=== Installing livekit-wakeword (PR #71 branch) ==="
uv pip install --python $venvPy --torch-backend=auto "livekit-wakeword[train,eval,export,voxcpm,listener] @ git+https://github.com/livekit/livekit-wakeword@refs/pull/71/head"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FATAL: install failed (exit $LASTEXITCODE)."
    exit 1
}

# --- 3. Fix webrtcvad (PR71 predates the webrtcvad-wheels fix on main) --
# Cannot be folded into step 2 above: verified that listing webrtcvad-wheels
# alongside the initial install just installs BOTH webrtcvad and
# webrtcvad-wheels side by side (different package names, so uv has no way
# to know they're substitutes for each other) -- whichever's file write
# happens to land last wins the same import path, non-deterministically,
# and in testing the broken one won. An explicit uninstall-then-install is
# the only reliable way to guarantee webrtcvad-wheels is what's actually
# importable afterward.
Write-Host "`n=== Swapping webrtcvad -> webrtcvad-wheels ==="
uv pip uninstall --python $venvPy webrtcvad
uv pip install --python $venvPy webrtcvad-wheels
if ($LASTEXITCODE -ne 0) {
    Write-Host "FATAL: webrtcvad-wheels install failed (exit $LASTEXITCODE)."
    exit 1
}

# --- 3b. Patch data/piper/synthesis.py -----------------------------------
# Two defects in the Piper path, neither of which has a config knob. Patched
# here so every stage runs as plain `livekit-wakeword <cmd> <config>` with no
# wrapper scripts. Idempotent: keyed off the marker comment.
#
#   a) get_phonemes() shells out to the espeak-ng binary once PER CLIP, for a
#      deterministic function of (text, voice) over a cycling list of at most a
#      few thousand phrases. At ~54ms per process spawn on Windows this was
#      ~39% of a batch and serialised the GPU. Measured effect of the cache:
#      ~1 clip/s -> ~71 clips/s end to end.
#
#   b) VITS computes `w = exp(logw) * length_scale` from the STOCHASTIC
#      duration predictor and clamps it only from BELOW. A rare draw becomes a
#      ~970-second utterance, and y_lengths.max() sizes the tensors for the
#      whole batch, so one bad sample inflates all of them: observed a 64-clip
#      batch requesting 4.4GB, exhausting VRAM and spilling into system RAM.
#      The patch scales an over-long utterance down proportionally, preserving
#      relative phoneme rhythm. 689 frames = 8.0s at 22050Hz / hop 256; the
#      natural maximum for these phrases is ~271 frames (3.1s), measured over
#      800 draws, so it only ever fires on a runaway.
#
# Both are genuine upstream bugs and worth filing against livekit-wakeword.
Write-Host "`n=== Patching piper/synthesis.py (phoneme cache + duration bound) ==="
$synth = & $venvPy -c "import livekit.wakeword.data.piper.synthesis as m; print(m.__file__)"
if (-not (Test-Path $synth)) {
    Write-Host "FATAL: could not locate synthesis.py (got '$synth')."
    exit 1
}
$src = Get-Content -Raw -Encoding UTF8 $synth
if ($src -match 'YUUKA-PATCH') {
    Write-Host "already patched, skipping."
} else {
    $needle = '    phonemes_str = _espeak_phonemize(text, voice)'
    $repl   = @'
    # YUUKA-PATCH (a): memoize the per-clip espeak subprocess.
    phonemes_str = _cached_espeak_phonemize(text, voice)
'@
    if ($src -notmatch [regex]::Escape($needle)) {
        Write-Host "FATAL: patch (a) anchor not found -- upstream changed, re-check the patch."
        exit 1
    }
    $src = $src.Replace($needle, $repl)
    $src = $src.Replace("def get_phonemes(", @'
@functools.lru_cache(maxsize=8192)
def _cached_espeak_phonemize(text: str, voice: str = "en-us") -> str:
    return _espeak_phonemize(text, voice)


def get_phonemes(
'@.TrimEnd() + "`n")
    $src = $src -replace '(?m)^import json', "import functools`nimport json"

    $needle2 = '    w = torch.exp(logw) * x_mask * length_scale'
    $repl2 = @'
    w = torch.exp(logw) * x_mask * length_scale
    # YUUKA-PATCH (b): bound runaway stochastic-duration draws. Upstream clamps
    # y_lengths from below only; an unlucky exp() produces a ~970s utterance and
    # y_lengths.max() then sizes the tensors for the entire batch.
    _total = torch.sum(w, [1, 2], keepdim=True)
    _cap = 689.0
    w = torch.where(_total > _cap, w * (_cap / _total), w)
'@
    if ($src -notmatch [regex]::Escape($needle2)) {
        Write-Host "FATAL: patch (b) anchor not found -- upstream changed, re-check the patch."
        exit 1
    }
    $src = $src.Replace($needle2, $repl2)
    Set-Content -Path $synth -Value $src -Encoding UTF8 -NoNewline
    Write-Host "patched $synth"
}

# --- 4. Verify everything, independently ---------------------------------
Write-Host "`n=== Verifying ==="

$webrtcvadOk = & $venvPy -c "import webrtcvad; print('OK')" 2>&1
if ($webrtcvadOk -notmatch "OK") {
    Write-Host "FATAL: webrtcvad import still broken:"
    Write-Host $webrtcvadOk
    exit 1
}
Write-Host "webrtcvad: OK"

$torchInfo = & $venvPy -c "import torch; print(torch.__version__, torch.cuda.is_available())" 2>&1
Write-Host "torch: $torchInfo"
if ($torchInfo -notmatch "True") {
    Write-Host "WARNING: torch.cuda.is_available() is not True. generate will be ~15-20x slower than it should be."
    Write-Host "Check: an NVIDIA GPU + driver must actually be present on this machine for --torch-backend=auto to find a CUDA build."
}

$env:PYTHONUTF8 = "1"
& $venvPy -m livekit.wakeword --help *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "FATAL: CLI smoke test failed (exit $LASTEXITCODE)."
    exit 1
}
Write-Host "CLI: OK"

# --- 5. Print the one manual step ---------------------------------------
Write-Host "`n=== Setup complete. One manual step remains: ==="
Write-Host "background_noise_source.opus (a real recorded background-noise source) is gitignored"
Write-Host "and was NOT transferred by cloning this repo. Copy it from the original machine to"
Write-Host "this repo's root, then chunk it (same command used originally, see TRAINING.md):"
Write-Host ""
Write-Host "    ffmpeg -y -i background_noise_source.opus -f segment -segment_time 8 -c copy wakeword_training\data\backgrounds_chunked\chunk_%04d.wav"
Write-Host ""
Write-Host "(destination folder is created automatically by ffmpeg's -f segment; if it errors,"
Write-Host "run: New-Item -ItemType Directory -Force -Path wakeword_training\data\backgrounds_chunked)"
Write-Host ""
Write-Host "After that, run setup/generate/augment/train/export/eval per TRAINING.md, e.g.:"
Write-Host "    `$env:PYTHONUTF8=`"1`""
Write-Host "    $venvPy -m livekit.wakeword setup --config wakeword_training/configs/yuuka_v1.yaml"
