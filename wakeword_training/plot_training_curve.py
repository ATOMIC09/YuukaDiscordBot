r"""Plot validation accuracy/recall over training time from a metrics.json.

train saves a JSON array of validation snapshots (step/phase/fpph/recall/
accuracy at threshold=0.5) but doesn't chart it itself. This turns that into
the same two-panel chart used throughout wake-word training runs so far.

Run with any Python that has matplotlib (the livekit-wakeword tool's own
Python does, via the `eval` extra):
    & "$env:APPDATA\uv\tools\livekit-wakeword\Scripts\python.exe" wakeword_training\plot_training_curve.py wakeword_training\output\yuuka_wakeword_v1\yuuka_wakeword_v1_metrics.json

Or point it at a model's output directory and it'll find the metrics.json:
    ... plot_training_curve.py wakeword_training\output\yuuka_wakeword_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_PHASE_COLORS = {1: "#2563eb", 2: "#d97706", 3: "#16a34a"}


def _resolve_metrics_path(target: Path) -> Path:
    if target.is_file():
        return target
    if target.is_dir():
        matches = sorted(target.glob("*_metrics.json"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SystemExit(
                f"Multiple *_metrics.json files in {target}, pass the exact file: "
                + ", ".join(str(m) for m in matches)
            )
        raise SystemExit(f"No *_metrics.json file found in {target}")
    raise SystemExit(f"Path not found: {target}")


def plot_training_curve(metrics_path: Path, out_path: Path | None = None) -> Path:
    data = json.loads(metrics_path.read_text())
    rows = [d for d in data if d["phase"] in (1, 2, 3)]
    if not rows:
        raise SystemExit(f"No phase 1-3 validation rows in {metrics_path}")

    model_name = metrics_path.stem.removesuffix("_metrics")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)

    for phase, color in _PHASE_COLORS.items():
        phase_rows = [d for d in rows if d["phase"] == phase]
        if not phase_rows:
            continue
        xs = [d["elapsed_s"] for d in phase_rows]
        ax1.plot(xs, [d["accuracy"] for d in phase_rows], "o-", color=color, label=f"Phase {phase} accuracy")
        ax2.plot(xs, [d["recall"] for d in phase_rows], "o-", color=color, label=f"Phase {phase} recall")

    ax1.axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="Chance (50%)")
    ax1.set_ylabel("Validation accuracy (threshold=0.5)")
    ax1.set_ylim(0.4, 1.0)
    ax1.set_title(f"{model_name} — validation accuracy/recall over training")
    ax1.legend(loc="lower right", fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.set_xlabel("Elapsed training time (s)")
    ax2.set_ylabel("Validation recall (threshold=0.5)")
    ax2.set_ylim(0.0, 1.0)
    ax2.legend(loc="lower right", fontsize=9)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()

    if out_path is None:
        out_path = metrics_path.with_name(f"{model_name}_training_curve.png")
    fig.savefig(str(out_path), dpi=150)
    plt.close(fig)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Path to a *_metrics.json file, or a model output directory containing one")
    parser.add_argument("-o", "--out", help="Output PNG path (default: <model_name>_training_curve.png next to the metrics file)")
    args = parser.parse_args()

    metrics_path = _resolve_metrics_path(Path(args.target))
    out_path = Path(args.out) if args.out else None
    saved = plot_training_curve(metrics_path, out_path)
    print(f"Saved {saved}")


if __name__ == "__main__":
    main()
