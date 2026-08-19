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
*head* of the utterance only — a wake word buried in the middle of a sentence
is almost always a false positive.

On a hit we return the rest of the sentence with the wake word removed, so
"ยูกะ ช่วยบอกเวลาหน่อย" reaches the LLM as "ช่วยบอกเวลาหน่อย".
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

# Leading filler left behind after the wake word is cut off.
_LEADING_JUNK = re.compile(r"^[\s,\.!?ๆฯ:;\-—…]+")


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
    head_chars: int = 16,
) -> WakeMatch:
    """
    Test whether *text* opens with one of *wake_words*.

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

    head = normalized[:head_chars]

    best_score = 0.0
    best_word = ""
    best_end = 0

    for word in wake_words:
        needle = normalize(word)
        if not needle:
            continue

        alignment = partial_ratio_alignment(needle, head)
        if alignment is None:
            continue

        if alignment.score <= best_score:
            continue

        best_score = alignment.score
        best_word = word
        # partial_ratio_alignment swaps its arguments when the first is the
        # longer one, which would make dest_end refer to the needle instead.
        # Wake words are short and head_chars is generous, so that only
        # happens on a near-empty utterance — consume the whole head there.
        best_end = alignment.dest_end if len(needle) <= len(head) else len(head)

    if best_score < threshold:
        return WakeMatch(False, best_score, best_word)

    # Translate the match end back into the original string.
    if best_end >= len(index_map):
        remainder = ""
    else:
        remainder = text[index_map[best_end] :]

    return WakeMatch(True, best_score, best_word, _LEADING_JUNK.sub("", remainder).strip())
