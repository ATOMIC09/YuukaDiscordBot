"""Compare wake-word models the way this bot actually uses them.

Why not just read eval.json
---------------------------
`livekit-wakeword eval` reports recall and FPPH at a *fixed threshold of 0.5*,
plus an `aut` summary. Both mislead when comparing models:

* **Fixed threshold.** A model whose scores sit higher shows both a higher
  recall and a higher FPPH without being better or worse — it is simply at a
  different point on the same curve. v2 looked like an FPPH regression against
  v1 for exactly this reason; rescored at matched FPPH it beat v1 everywhere.
* **AUT** integrates the DET curve over false-positive *rates* from 0 to 1.
  With 2-second clips, FPR 1% is already ~18 FPPH, so every operating point
  this bot could deploy at lives in the first fraction of a percent of that
  axis. A model can win AUT decisively while being far worse everywhere real.
  (Observed: v3a beat v2 on AUT by 18% while being 20 points worse at 0.1 FPPH.)

So: fix an FPPH budget, then compare recall. That is what this prints.

Reading the output for THIS bot
-------------------------------
utils/wake_acoustic.py uses the model as a *pre-filter* deciding whether a
closed speech segment is worth sending to STT — not as the trigger. The trigger
is utils/wake.py's fuzzy text match on the transcript. That inverts the usual
wake-word priorities:

* A **miss** silently drops a real summon. This is the failure that matters.
* A **false accept** costs one wasted transcription, which the text match then
  discards. It is a cost, not a UX bug.

So read the HIGH end of the budget table (25-250 FPPH), not the 0.1-1.0 range a
standalone always-on wake word would target.

Two caveats on the absolute numbers:
* Each row's threshold is set by the top-N negative clips, where N is printed
  as `#FP`. At small N the threshold rides on a handful of samples, so the
  bootstrap interval is wide. Rank models on rows with N in the hundreds.
* Every figure is per isolated 2-second clip. Deployment slides a 2s window at
  1s stride across a segment and takes the max (`_predict_max`), which raises
  both recall and false accepts. Use this to compare models, not to predict
  absolute deployed rates.

Usage (from repo root):
    wakeword_training\\.venv\\Scripts\\python.exe wakeword_training\\compare_models.py
    ... --models yuuka_wakeword_v2 yuuka_wakeword_v3a --bootstrap 400
    ... --models models/wake_word/yuuka_wakeword.onnx yuuka_wakeword_v2
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CLIP_SECONDS = 2.0
DEFAULT_BUDGETS = (0.25, 1.0, 2.0, 25.0, 50.0, 91.0, 150.0)


def resolve_model(spec: str) -> tuple[str, Path]:
    """Accept a run name, a path to an .onnx, or a repo-relative path."""
    candidate = Path(spec)
    if candidate.suffix == ".onnx":
        for base in (Path.cwd(), ROOT.parent):
            if (base / candidate).exists():
                return candidate.stem, (base / candidate).resolve()
        if candidate.exists():
            return candidate.stem, candidate.resolve()
        raise SystemExit(f"Model not found: {spec}")

    onnx = OUTPUT / spec / f"{spec}.onnx"
    if not onnx.exists():
        raise SystemExit(f"Model not found: {onnx}")
    return spec, onnx


def load_eval_set(eval_from: str) -> tuple[np.ndarray, np.ndarray, float]:
    """Load one run's held-out features, mirroring eval/evaluate.py exactly.

    Every model is scored on this ONE set so the numbers are comparable. Runs
    that reuse another run's features (v3* hardlink v2's) share it already.
    """
    model_dir = OUTPUT / eval_from
    pos = np.load(model_dir / "positive_features_test.npy")

    parts = [np.load(model_dir / "negative_features_test.npy")]
    bg = model_dir / "background_noise_features_test.npy"
    if bg.exists():
        parts.append(np.load(bg))

    val_path = ROOT / "data" / "features" / "validation_set_features.npy"
    if val_path.exists():
        val = np.load(val_path)
        if val.ndim == 2:  # same trim the library applies
            val = val[: (val.shape[0] // 16) * 16].reshape(-1, 16, 96)
        parts.append(val)

    neg = np.concatenate(parts, axis=0)
    return pos, neg, neg.shape[0] * CLIP_SECONDS / 3600.0


def score(onnx_path: Path, features: np.ndarray, cache_dir: Path, batch: int = 2048) -> np.ndarray:
    """Run the ONNX classifier, memoised on (model bytes, feature bytes)."""
    import onnxruntime as ort

    key = hashlib.sha256()
    key.update(onnx_path.read_bytes())
    key.update(str(features.shape).encode())
    key.update(features[:64].tobytes())
    cached = cache_dir / f"{key.hexdigest()[:24]}.npy"
    if cached.exists():
        return np.load(cached)

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    out = np.concatenate([
        session.run(None, {name: features[i : i + batch].astype(np.float32)})[0].squeeze(-1)
        for i in range(0, len(features), batch)
    ])
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(cached, out)
    return out


def recall_at_budget(pos: np.ndarray, neg: np.ndarray, budget: float, hours: float) -> tuple[float, float]:
    """Highest recall achievable while staying within `budget` false positives/hour.

    Picks the threshold directly from the sorted negative scores rather than
    scanning a fixed grid: the library's 0.01-step scan is far too coarse for a
    model whose useful range is compressed near 1.0.
    """
    allowed = int(budget * hours)
    ordered = np.sort(neg)[::-1]
    if allowed >= len(ordered):
        return 1.0, 0.0
    threshold = float(np.nextafter(ordered[allowed], 1.0))
    return float(np.mean(pos >= threshold)), threshold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--models", nargs="+", help="Run names and/or .onnx paths")
    parser.add_argument("--eval-from", default="yuuka_wakeword_v2",
                        help="Run whose held-out features form the common set")
    parser.add_argument("--budgets", nargs="+", type=float, default=list(DEFAULT_BUDGETS))
    parser.add_argument("--bootstrap", type=int, default=400,
                        help="Resamples for confidence intervals; 0 to skip")
    parser.add_argument("--baseline", help="Model to report paired differences against")
    args = parser.parse_args(argv)

    specs = args.models
    if not specs:
        specs = sorted(d.name for d in OUTPUT.iterdir()
                       if d.is_dir() and (d / f"{d.name}.onnx").exists())
        deployed = ROOT.parent / "models" / "wake_word" / "yuuka_wakeword.onnx"
        if deployed.exists():
            specs.append(str(deployed))
    # Dedupe on CONTENT, not path: the promoted copy under models/wake_word/ is
    # a separate file with identical bytes, so samefile() would not catch it,
    # and two columns sharing a name collide in `scores` below.
    resolved: list[tuple[str, Path]] = []
    by_digest: dict[str, str] = {}
    for spec in specs:
        name, path = resolve_model(spec)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in by_digest:
            print(f"note: {spec} is byte-identical to {by_digest[digest]}, skipping")
            continue
        by_digest[digest] = name
        resolved.append((name, path))

    pos_f, neg_f, hours = load_eval_set(args.eval_from)
    cache = ROOT / "output" / ".score_cache"
    print(f"eval set: {args.eval_from} -- {len(pos_f)} pos / {len(neg_f)} neg / {hours:.2f} h")
    print(f"models  : {', '.join(n for n, _ in resolved)}\n")

    scores = {}
    for name, path in resolved:
        scores[name] = (score(path, pos_f, cache), score(path, neg_f, cache))

    names = [n for n, _ in resolved]
    width = max(len(n) for n in names) + 12
    header = f"{'fpph':>7} {'#FP':>5} |" + "".join(f"{n:>{width}} |" for n in names)
    print("Recall at matched FPPH budgets (threshold chosen per model)")
    print(header)
    print("-" * len(header))

    rng = np.random.default_rng(0)
    for budget in args.budgets:
        line = f"{budget:>7.2f} {int(budget * hours):>5} |"
        for name in names:
            pos_s, neg_s = scores[name]
            recall, threshold = recall_at_budget(pos_s, neg_s, budget, hours)
            if args.bootstrap:
                draws = np.array([
                    recall_at_budget(pos_s[rng.integers(0, len(pos_s), len(pos_s))],
                                     neg_s[rng.integers(0, len(neg_s), len(neg_s))],
                                     budget, hours)[0]
                    for _ in range(args.bootstrap)
                ])
                lo, hi = np.percentile(draws, [5, 95])
                cell = f"{recall:>6.1%} [{lo:>5.1%},{hi:>5.1%}] @{threshold:.4f}"
            else:
                cell = f"{recall:>6.1%} @{threshold:.4f}"
            line += f"{cell:>{width}} |"
        print(line)

    if args.baseline and args.bootstrap:
        base = args.baseline if args.baseline in scores else resolve_model(args.baseline)[0]
        if base not in scores:
            raise SystemExit(f"--baseline {args.baseline} is not among the compared models")
        print(f"\nPaired difference vs {base} (90% CI; 'noise' means the interval spans zero)")
        for budget in args.budgets:
            cells = []
            for name in names:
                if name == base:
                    continue
                diff = np.empty(args.bootstrap)
                for b in range(args.bootstrap):
                    pi = rng.integers(0, len(pos_f), len(pos_f))
                    ni = rng.integers(0, len(neg_f), len(neg_f))
                    diff[b] = (recall_at_budget(scores[name][0][pi], scores[name][1][ni], budget, hours)[0]
                               - recall_at_budget(scores[base][0][pi], scores[base][1][ni], budget, hours)[0])
                lo, hi = np.percentile(diff, [5, 95])
                verdict = "SIGNIFICANT" if lo > 0 or hi < 0 else "noise"
                cells.append(f"{name}: {diff.mean():+6.1%} [{lo:+6.1%},{hi:+6.1%}] {verdict}")
            print(f"{budget:>7.2f} | " + " | ".join(cells))

    print("\nThis bot uses the model as a pre-filter ahead of STT (see the module")
    print("docstring): a miss drops a real summon, a false accept costs one wasted")
    print("transcription. Read the HIGH budget rows, and rank on rows where #FP is")
    print("in the hundreds -- small #FP means the threshold rests on a few samples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
