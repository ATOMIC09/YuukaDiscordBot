"""Per-phrase recall and hard-negative false accepts for a trained wake-word model.

Why this exists
---------------
`eval.json` reports one pooled recall number across all positive clips. With a
mixed short/long target set ("yuuka" and "hey yuuka") that number is an average
over two populations that behave very differently — takoyaki's V1 measured 95.8%
on "tako-yaki" and 54.6% on "hey tako" *in the same model*, an aggregate of 81.6%
that describes neither. compare_models.py has the same limitation: it works on
pooled feature arrays with no phrase labels.

This script scores the original (un-augmented) `positive_test` clips one at a
time and groups them by phrase. Clip N was synthesized from
`target_phrases[N % len(target_phrases)]` (round-robin in run_generate), so the
label comes straight from the filename — no dependence on augment ordering.

It also splits false accepts into curated hard negatives (config's
`custom_negative_phrases`) vs auto-generated CMUDict neighbours. That
distinction is the whole point of the v3 negative work: a model can look clean
on auto negatives while failing on the near-misses that actually matter.

Usage (from the repo root):

    python wakeword_training/eval_per_phrase.py --config wakeword_training/configs/yuuka_v3.yaml

    --thresholds   comma-separated (default 0.05,0.1,0.2,0.3,0.5,0.7)
    --limit        cap clips per split for a quick pass (default: all)
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

CLIP_RE = re.compile(r"clip_(\d+)\.wav$")
DEFAULT_THRESHOLDS = "0.05,0.1,0.2,0.3,0.5,0.7"


def original_clips(split_dir: Path) -> list[tuple[int, Path]]:
    """Return [(index, path)] for un-augmented clip_NNNNNN.wav files, sorted by index.

    Augmentation rounds are written as clip_NNNNNN_rN.wav; those are excluded so
    the round-robin phrase mapping stays exact.
    """
    out: list[tuple[int, Path]] = []
    for p in sorted(split_dir.glob("clip_*.wav")):
        m = CLIP_RE.search(p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def score_clips(
    clips: list[tuple[int, Path]],
    onnx_path: Path,
    providers: list[str],
) -> np.ndarray:
    """Score each clip through mel -> speech_embedding -> classifier ONNX."""
    import onnxruntime as ort
    from livekit.wakeword.data.features import _extract_one
    from livekit.wakeword.models.feature_extractor import (
        MelSpectrogramFrontend,
        SpeechEmbedding,
    )
    from livekit.wakeword.resources import get_embedding_model_path, get_mel_model_path

    mel = MelSpectrogramFrontend(onnx_path=get_mel_model_path(), execution_providers=providers)
    emb = SpeechEmbedding(onnx_path=get_embedding_model_path(), execution_providers=providers)
    sess = ort.InferenceSession(str(onnx_path), providers=providers)
    in_name = sess.get_inputs()[0].name

    feats = np.stack([_extract_one(p, mel, emb) for _, p in clips]).astype(np.float32)
    scores = sess.run(None, {in_name: feats})[0]
    return np.asarray(scores).reshape(-1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    from livekit.wakeword.config import WakeWordConfig

    config = WakeWordConfig(**yaml.safe_load(io.open(args.config, encoding="utf-8")))
    model_dir = config.model_output_dir
    onnx_path = model_dir / f"{config.model_name}.onnx"
    if not onnx_path.exists():
        raise SystemExit(f"No exported model at {onnx_path}. Run the export stage first.")

    providers = list(config.eval.execution_providers)
    thresholds = [float(t) for t in args.thresholds.split(",")]
    phrases = config.target_phrases

    # --- positives, grouped by the phrase that produced them -----------------
    pos = original_clips(model_dir / "positive_test")
    if not pos:
        raise SystemExit(f"No clips found in {model_dir / 'positive_test'}")
    if args.limit:
        pos = pos[: args.limit]
    pos_scores = score_clips(pos, onnx_path, providers)

    by_phrase: dict[str, list[float]] = defaultdict(list)
    for (idx, _), s in zip(pos, pos_scores):
        by_phrase[phrases[idx % len(phrases)]].append(float(s))

    print(f"\nModel: {config.model_name}   positives scored: {len(pos)}")
    print("\nPER-PHRASE RECALL")
    head = "  ".join(f"@{t:<5g}" for t in thresholds)
    print(f"{'phrase':<16}{'n':>6}  {'mean':>7}  {head}")
    print("-" * (33 + 9 * len(thresholds)))
    for ph in phrases:
        sc = np.array(by_phrase.get(ph, []))
        if sc.size == 0:
            continue
        cells = "  ".join(f"{100.0 * (sc >= t).mean():5.1f}%" for t in thresholds)
        print(f"{ph:<16}{sc.size:>6}  {sc.mean():7.4f}  {cells}")

    # Short vs long is the question v3 was built to answer.
    print("\nSHORT vs LONG")
    for label, keep in (("short", False), ("hey ...", True)):
        sc = np.array(
            [s for ph, lst in by_phrase.items() if ph.startswith("hey ") == keep for s in lst]
        )
        if sc.size == 0:
            continue
        cells = "  ".join(f"{100.0 * (sc >= t).mean():5.1f}%" for t in thresholds)
        print(f"{label:<16}{sc.size:>6}  {sc.mean():7.4f}  {cells}")

    # --- negatives, split curated vs auto ------------------------------------
    neg = original_clips(model_dir / "negative_test")
    if args.limit:
        neg = neg[: args.limit]
    if not neg:
        print("\n(no negative_test clips found — skipping false-accept breakdown)")
        return 0

    neg_scores = score_clips(neg, onnx_path, providers)

    # run_generate builds the pool as generate_adversarial_phrases(...) +
    # custom_negative_phrases, and assigns clips `pool[i % len(pool)]`. The auto
    # half is shuffled without a seed so its ORDER cannot be reproduced, but its
    # LENGTH is deterministic (it comes from a set of CMUDict neighbours) and the
    # curated half is always appended at the tail. That is enough to classify any
    # clip from its index alone — no manifest needed.
    groups: dict[str, list[float]] = defaultdict(list)
    if config.custom_negative_phrases:
        from livekit.wakeword.data.generate import generate_adversarial_phrases

        n_auto = len(generate_adversarial_phrases(target_phrases=config.target_phrases))
        n_pool = n_auto + len(config.custom_negative_phrases)
        for (idx, _), s in zip(neg, neg_scores):
            groups["curated hard" if idx % n_pool >= n_auto else "auto"].append(float(s))
        print(
            f"\n(pool = {n_auto} auto + {len(config.custom_negative_phrases)} curated "
            f"= {n_pool}; validation is {len(neg)} clips, so it cycles "
            f"{len(neg) / n_pool:.1f}x and reaches every curated phrase)"
        )
    else:
        groups = {"all negatives": [float(s) for s in neg_scores]}

    print("\nFALSE ACCEPTS BY NEGATIVE TYPE")
    print(f"{'type':<16}{'n':>6}  {'mean':>7}  {head}")
    print("-" * (33 + 9 * len(thresholds)))
    for label in ("curated hard", "auto", "all negatives"):
        if label not in groups:
            continue
        sc = np.array(groups[label])
        cells = "  ".join(f"{100.0 * (sc >= t).mean():5.1f}%" for t in thresholds)
        print(f"{label:<16}{sc.size:>6}  {sc.mean():7.4f}  {cells}")

    print(
        "\nRead the curated-hard row, not the auto row: it is the one that predicts "
        "real false wake-ups.\nv1/v2 had no curated negatives in validation at all, so "
        "their fpph figures are not comparable."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
