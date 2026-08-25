"""Validate wake-word spellings before spending GPU hours generating from them.

Piper synthesizes through two stages that both silently reshape your text:

1. `normalize_phrases_for_piper` (livekit/wakeword/data/tts/piper_backend.py:62)
   splits words CMUDict does not know into known subwords. "yuka" becomes
   "yu ka" — two words with a boundary, which is not the wake word. This check
   runs with no external dependencies.

2. `espeak-ng --ipa` turns the normalized text into phonemes. This is what the
   voice actually says, and it is the only way to know whether "yuucah" and
   "yoocah" are distinct pronunciations or the same one. Requires espeak-ng on
   PATH; skipped with a warning if absent.

It also flags any `custom_negative_phrases` entry that phonemizes identically to
a target — the
"taco yaki" mistake takoyaki caught by ear, where the same audio is trained as
both classes and blunts the decision boundary. Comparison is on the bare phoneme
sequence, so a difference of only a word boundary or stress mark still counts.

Usage (from the repo root):

    python wakeword_training/check_pronunciation.py --config wakeword_training/configs/yuuka_v3.yaml

Exit code is non-zero if a target gets split or a target/negative homophone pair
is found, so this can gate a run.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

def espeak_ipa(texts: list[str], voice: str = "en-us") -> dict[str, str | None]:
    """Phonemize each text with espeak-ng, matching how Piper calls it.

    Batched through a temp file (`espeak-ng -f`), which emits one output line per
    input line. Spawning one process per phrase takes minutes for a 200-entry
    negative list on Windows; this is a single spawn. Falls back to per-phrase
    calls if the line counts do not line up, since the batch path depends on
    espeak preserving the 1:1 line mapping.
    """
    exe = shutil.which("espeak-ng")
    if not exe:
        return {t: None for t in texts}
    if not texts:
        return {}

    def _one(t: str) -> str | None:
        try:
            r = subprocess.run(
                [exe, "--ipa", "-q", "-v", voice, t],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            return r.stdout.strip() or None
        except (subprocess.SubprocessError, OSError):
            return None

    tmp = None
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8", newline="\n"
        ) as fh:
            tmp = Path(fh.name)
            fh.write("\n".join(texts) + "\n")
        r = subprocess.run(
            [exe, "--ipa", "-q", "-v", voice, "-f", str(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        if len(lines) == len(texts):
            return dict(zip(texts, lines))
    except (subprocess.SubprocessError, OSError):
        pass
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

    return {t: _one(t) for t in texts}


def _bare(ipa: str) -> str:
    """Phoneme sequence with stress marks and word boundaries removed."""
    return ipa.replace("ˈ", "").replace("ˌ", "").replace(" ", "")


def _has_doubled_nucleus(ipa: str) -> bool:
    """True if espeak produced two adjacent identical vowel nuclei.

    Stress marks and word spaces sit between the glides ("jˈuːjuːkə",
    "jˈuː jˈuːnə"), so they are stripped before the comparison.
    """
    bare = ipa.replace("ˈ", "").replace("ˌ", "").replace(" ", "")
    return "juːjuː" in bare or "uːuː" in bare


def load_curated(config: object) -> list[str]:
    """Hard negatives come straight from the config's custom_negative_phrases."""
    seen, phrases = set(), []
    for line in config.custom_negative_phrases:  # type: ignore[attr-defined]
        if line and line not in seen:
            seen.add(line)
            phrases.append(line)
    return phrases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--voice", default="en-us")
    args = ap.parse_args(argv)

    from livekit.wakeword.config import WakeWordConfig
    from livekit.wakeword.data.piper.text import normalize_phrases_for_piper

    config = WakeWordConfig(**yaml.safe_load(io.open(args.config, encoding="utf-8")))
    targets = config.target_phrases
    curated = load_curated(config)

    failed = False

    # --- stage 1: CMUDict normalization --------------------------------------
    print("TARGET PHRASES — CMUDict normalization")
    print(f"{'spelling':<18}{'what Piper actually says':<28}")
    print("-" * 50)
    normalized = normalize_phrases_for_piper(targets)
    for src, dst in zip(targets, normalized):
        mark = "" if src == dst else "   <-- SPLIT, will not say the wake word"
        if src != dst:
            failed = True
        print(f"{src:<18}{dst:<28}{mark}")

    if not shutil.which("espeak-ng"):
        print(
            "\nespeak-ng not found on PATH — stage 2 (IPA) skipped.\n"
            "  Windows: download the .msi from github.com/espeak-ng/espeak-ng/releases\n"
            "           and make sure the install dir is on PATH\n"
            "  macOS:   brew install espeak-ng\n"
            "  Linux:   sudo apt install espeak-ng\n"
            "Piper CANNOT generate audio without it — the generate stage will fail."
        )
        return 1 if failed else 0

    # --- stage 2: espeak IPA -------------------------------------------------
    tgt_ipa = espeak_ipa(normalized, args.voice)
    print("\nTARGET PHRASES — espeak IPA")
    for src, dst in zip(targets, normalized):
        print(f"{src:<18}{tgt_ipa.get(dst) or '(no output)'}")

    distinct = {v for v in tgt_ipa.values() if v}
    print(f"\n{len(distinct)} distinct pronunciation(s) across {len(targets)} spellings.")
    if len(distinct) < 2:
        print(
            "  Only one pronunciation — the extra spellings add nothing. Vary them or "
            "drop them; takoyaki used tako-yaki/tahkoyaki precisely to get two."
        )

    # --- stage 2b: doubled-glide / doubled-vowel artifacts --------------------
    #
    # espeak reads a doubled vowel letter as two separate nuclei: "yuuka" becomes
    # /jˈuːjuːkə/ ("yoo-YOO-kuh"), three syllables instead of two. The spelling
    # looks obviously right and the audio is obviously wrong, which is exactly
    # the combination that gets generated for 20 hours before anyone notices.
    doubled = [
        (src, p)
        for src, dst in zip(targets, normalized)
        if (p := tgt_ipa.get(dst)) and _has_doubled_nucleus(p)
    ]
    if doubled:
        failed = True
        print("\n  DOUBLED-NUCLEUS ARTIFACT — these say an extra syllable:")
        for src, p in doubled:
            print(f"    {src:<18}{p}")
        print("    Respell without the doubled vowel letter (e.g. 'yuuka' -> 'yoocah').")

    # --- stage 3: homophone collisions ---------------------------------------
    if curated:
        neg_norm = normalize_phrases_for_piper(curated)
        neg_ipa = espeak_ipa(neg_norm, args.voice)
        # Compare on the bare phoneme sequence, not the raw IPA string. espeak
        # marks word boundaries with a space and stress with ˈ/ˌ, so "yoo ka"
        # (jˈuː kˈɑː) and target "yoo-cah" (jˈuːkˈɑː) are the SAME phonemes
        # j-uː-k-ɑː and differ only in spacing — a literal string compare misses
        # it, and after synthesis a word boundary is at most a brief pause.
        # Two real collisions ("yoo ka", "yoo kha", romanized ยูกะ/ยูคะ) shipped
        # in the first negative list because of exactly this.
        by_ipa = {_bare(v): k for k, v in tgt_ipa.items() if v}
        collisions = [
            (orig, neg_ipa[n], by_ipa[_bare(neg_ipa[n])])
            for orig, n in zip(curated, neg_norm)
            if neg_ipa.get(n) and _bare(neg_ipa[n]) in by_ipa
        ]
        print(f"\nHOMOPHONE CHECK — {len(curated)} hard negatives vs {len(targets)} targets")
        if collisions:
            failed = True
            print("  COLLISIONS (same phonemes as a target — remove these):")
            for orig, ipa, tgt in collisions:
                print(f"    {orig:<24}{ipa:<18}== target {tgt!r}")
        else:
            print("  none — no negative phonemizes identically to a target.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
