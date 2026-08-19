"""
utils/wake.py
Wake-word gating for voice input.

Why fuzzy matching
------------------
Speech recognition does not spell a name the same way twice, and Thai makes
that worse: "Yuuka" plausibly comes back as ยูกะ, ยูก้า, ยูคะ, ยุกะ or ยูก๊ะ
depending on how the sentence was said. An exact string check fails constantly.

Japanese adds a second axis: the same name is written ユーカ, ユウカ or ゆうか
depending on the surrounding sentence, and those share no characters with each
other in the eyes of a character-level matcher — a katakana line scores 0
against a hiragana variant, not "close". Normalisation folds the scripts
together so one listed variant covers all of them. Nothing folds kanji, though,
so a name that comes back as 優花 still needs its own entry in the list.
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

# Japanese writes the same sounds three ways, and Whisper picks whichever the
# surrounding sentence suggests: ユーカ, ユウカ, ゆうか are one name spelled by
# three different rules. Katakana folds onto hiragana by a fixed offset (the
# two syllabaries are laid out in the same order), so one listed variant covers
# both scripts — the same trick as stripping Thai tone marks above.
_KATAKANA_FIRST, _KATAKANA_LAST, _KANA_OFFSET = "ァ", "ヶ", 0x60

# The 長音符 lengthens whatever vowel precedes it, so ユー and ユウ are the same
# sound written two ways. Spelling it out as that vowel collapses them; the
# alternative — dropping it — would instead split ユーカ from ユウカ.
_KANA_VOWEL: dict[str, str] = {}
for _row, _vowel in (
    ("あかがさざただなはばぱまやらわゃゕ", "あ"),
    ("いきぎしじちぢにひびぴみり", "い"),
    ("うくぐすずつづぬふぶぷむゆるゅ", "う"),
    ("えけげせぜてでねへべぺめれゑゖ", "え"),
    ("おこごそぞとどのほぼぽもよろをょ", "お"),
):
    for _kana in _row:
        _KANA_VOWEL[_kana] = _vowel

# A needle this short must effectively match exactly — see `_floor`.
_SHORT_NEEDLE_CHARS = 3
_SHORT_NEEDLE_FLOOR = 90

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

    Every rule here is one character in, at most one character out, so the map
    stays aligned no matter what it rewrites.
    """
    normalized_chars: list[str] = []
    index_map: list[int] = []

    for i, ch in enumerate(unicodedata.normalize("NFC", text)):
        if _THAI_MARKS.match(ch) or _NOISE.match(ch):
            continue

        ch = ch.lower()
        if _KATAKANA_FIRST <= ch <= _KATAKANA_LAST:
            ch = chr(ord(ch) - _KANA_OFFSET)
        elif ch == "ー":
            # Lengthens the previous sound, so it only means anything after a
            # kana — after a Latin letter or at the start of a line it is a
            # dash the ASR left behind, and gets dropped.
            previous = normalized_chars[-1] if normalized_chars else ""
            ch = _KANA_VOWEL.get(previous, "")
            if not ch:
                continue

        normalized_chars.append(ch)
        index_map.append(i)

    return "".join(normalized_chars), index_map


def normalize(text: str) -> str:
    """Normalised form used for matching. Exposed for logging and tests."""
    return _normalize_with_map(text)[0]


def _floor(needle: str, threshold: int) -> int:
    """
    The score *needle* must reach. Short ones have to be near-exact.

    `partial_ratio` is coarse on a short needle: against three characters the
    only reachable scores are 100, 80 and 67, so the default threshold of 80
    means "one character in three is wrong" — which in Japanese is a different
    word entirely. ゆうか sits at exactly 80 against ユーザー, ユーチューブ and
    every other ユー… word, while a real summons scores 100. Thai and romaji
    variants are four characters or more and keep the configured threshold.
    """
    if len(needle) <= _SHORT_NEEDLE_CHARS:
        return max(threshold, _SHORT_NEEDLE_FLOOR)
    return threshold


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

    # Best score seen at all, reported even on a miss so the threshold can be
    # tuned from the logs.
    best_score = 0.0
    best_word = ""
    # Best score that also cleared its own floor — the actual match.
    match_score = 0.0
    match_word = ""
    match_start = 0
    match_end = 0

    for word in wake_words:
        needle = normalize(word)
        if not needle:
            continue

        alignment = partial_ratio_alignment(needle, haystack)
        if alignment is None:
            continue

        score = alignment.score
        if score > best_score:
            best_score, best_word = score, word

        if score < _floor(needle, threshold) or score <= match_score:
            continue

        match_score = score
        match_word = word
        # partial_ratio_alignment swaps its arguments when the first is the
        # longer one, which would make dest_start/dest_end refer to the needle
        # instead. Wake words are short, so that only happens on a near-empty
        # utterance — treat the whole thing as the name there.
        if len(needle) <= len(haystack):
            match_start, match_end = alignment.dest_start, alignment.dest_end
        else:
            match_start, match_end = 0, len(haystack)

    if not match_word:
        return WakeMatch(False, best_score, best_word)

    # Translate the matched span back into the original string and cut it out,
    # keeping whatever was said on either side of the name.
    cut_from = index_map[match_start] if match_start < len(index_map) else len(text)
    cut_to = index_map[match_end] if match_end < len(index_map) else len(text)
    remainder = f"{text[:cut_from]} {text[cut_to:]}"

    remainder = _GAP.sub(" ", remainder)
    return WakeMatch(True, match_score, match_word, _EDGE_JUNK.sub("", remainder).strip())
