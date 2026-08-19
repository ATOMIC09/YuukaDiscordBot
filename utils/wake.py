"""
utils/wake.py
Wake-word gating for voice input.

Why fuzzy matching
------------------
Speech recognition does not spell a name the same way twice, and Thai makes
that worse: "Yuuka" plausibly comes back as ยูกะ, ยูก้า, ยูคะ, ยุกะ or ยูก๊ะ
depending on how the sentence was said. An exact string check fails constantly.
So we normalise away the noise that carries no sound (tone marks, spacing,
punctuation, case), then fuzzy-match a list of spelling variants against the
utterance.

Why the whole utterance, not just its head
------------------------------------------
Thai puts the vocative at the end at least as often as the front — "แล้วอีก
แบบคืออะไรล่ะยูกะ" is a perfectly normal way to address her — so matching only
the first few characters misses half of real summons (that example scores 29
on the head, 100 on the whole line). Scanning everything costs less precision
than it looks: the phrase this collides with, "อยู่กับ", scores 75 either way,
because it is a near-miss of the *name*, not an artefact of where we looked.
The default threshold of 80 sits in that gap. `head_chars` is still there for
a room noisy enough to need it.

On a hit we return the sentence with the wake word cut out, wherever it was,
so "ยูกะ ช่วยบอกเวลาหน่อย" and "ช่วยบอกเวลาหน่อยยูกะ" both reach the LLM as
"ช่วยบอกเวลาหน่อย".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz.fuzz import partial_ratio_alignment

# Thai marks that sit above/below a consonant and do not change which sound
# the ASR heard — tone marks, maitaikhu, thanthakhat, nikhahit. Stripping them
# collapses ยูก้า and ยูก๊ะ onto their unmarked forms so the variant list stays
# short.
_THAI_MARKS = re.compile(r"[็-๎]")

# Everything that is not a letter, digit, or Thai character.
_NOISE = re.compile(r"[^\w฀-๿]+", re.UNICODE)

# Filler left behind on either side once the wake word is cut out.
_EDGE_JUNK = re.compile(r"^[\s,\.!?ๆฯ:;\-—…]+|[\s,:;\-—]+$")
# Cutting a name out of the middle leaves a double space behind.
_GAP = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class WakeMatch:
    """Result of testing one utterance against the wake words."""

    matched: bool
    score: float
    word: str = ""
    remainder: str = ""

    def __bool__(self) -> bool:
        return self.matched


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """
    Normalise *text* for matching and return the normalised string alongside
    an index map, so a match position can be translated back to an offset in
    the original string.

    ``index_map[i]`` is the index in *text* of the character that produced
    ``normalised[i]``.
    """
    normalized_chars: list[str] = []
    index_map: list[int] = []

    for i, ch in enumerate(unicodedata.normalize("NFC", text)):
        if _THAI_MARKS.match(ch) or _NOISE.match(ch):
            continue
        normalized_chars.append(ch.lower())
        index_map.append(i)

    return "".join(normalized_chars), index_map


def normalize(text: str) -> str:
    """Normalised form used for matching. Exposed for logging and tests."""
    return _normalize_with_map(text)[0]


def detect(
    text: str,
    wake_words: list[str],
    *,
    threshold: int = 80,
    head_chars: int = 0,
) -> WakeMatch:
    """
    Test whether *text* contains one of *wake_words*.

    *head_chars* limits the search to the first N characters; 0 — the default —
    searches the whole utterance, which is what catches a name spoken at the
    end of a sentence.

    Returns a :class:`WakeMatch` whose ``score`` is the best match found even
    when nothing cleared *threshold* — log it to tune the threshold against
    what your speakers' mics and accents actually produce.
    """
    if not text or not wake_words:
        return WakeMatch(False, 0.0)

    # NFC normalisation can change length, so map indices through the same
    # normalisation the matcher sees.
    normalized, index_map = _normalize_with_map(text)
    if not normalized:
        return WakeMatch(False, 0.0)

    haystack = normalized[:head_chars] if head_chars > 0 else normalized

    best_score = 0.0
    best_word = ""
    best_start = 0
    best_end = 0

    for word in wake_words:
        needle = normalize(word)
        if not needle:
            continue

        alignment = partial_ratio_alignment(needle, haystack)
        if alignment is None:
            continue

        if alignment.score <= best_score:
            continue

        best_score = alignment.score
        best_word = word
        # partial_ratio_alignment swaps its arguments when the first is the
        # longer one, which would make dest_start/dest_end refer to the needle
        # instead. Wake words are short, so that only happens on a near-empty
        # utterance — treat the whole thing as the name there.
        if len(needle) <= len(haystack):
            best_start, best_end = alignment.dest_start, alignment.dest_end
        else:
            best_start, best_end = 0, len(haystack)

    if best_score < threshold:
        return WakeMatch(False, best_score, best_word)

    # Translate the matched span back into the original string and cut it out,
    # keeping whatever was said on either side of the name.
    cut_from = index_map[best_start] if best_start < len(index_map) else len(text)
    cut_to = index_map[best_end] if best_end < len(index_map) else len(text)
    remainder = f"{text[:cut_from]} {text[cut_to:]}"

    remainder = _GAP.sub(" ", remainder)
    return WakeMatch(True, best_score, best_word, _EDGE_JUNK.sub("", remainder).strip())
