"""The wake-word matcher: ASR never spells her name the same way twice."""

import pytest

from bot.config import config
from utils.wake import detect, normalize

WORDS = config.stt_wake_words


def hit(text, **kwargs):
    return detect(text, WORDS, threshold=80, anywhere=True, **kwargs)


@pytest.mark.parametrize(
    "text",
    ["ยูกะ", "ยูก้า", "ยูก๊ะ", "ยุกะ", "ยูคะ", "Yuuka", "yuka", "ユーカ", "ユウカ", "ゆうか", "ゆーか"],
)
def test_spellings_of_her_name_match(text):
    assert hit(text)


@pytest.mark.parametrize("text", ["อยู่กับเพื่อนที่ห้างเมื่อวาน", "วันนี้อากาศดีจัง", "ผมจะไปกินข้าว"])
def test_ordinary_thai_does_not_match(text):
    match = hit(text)
    assert not match
    assert match.score < 80  # "อยู่กับ" scores 75, which is why the threshold is 80


@pytest.mark.parametrize("text", ["ユーザー", "ユーチューブ", "ユーモア"])
def test_short_japanese_needle_needs_a_near_exact_match(text):
    # ゆうか hits exactly 80 on every ユー… word, so a three-character needle must score 90.
    assert not hit(text)


@pytest.mark.parametrize("text", ["a", "u", "ยู", "eh"])
def test_a_clipped_fragment_is_not_her_name(text):
    # partial_ratio gives 100 to any string contained in the name; a lone letter summoned her.
    assert not hit(text)


def test_name_at_the_start_is_cut_out():
    match = hit("ยูกะ ช่วยบอกเวลาหน่อย")
    assert match and match.remainder == "ช่วยบอกเวลาหน่อย"


def test_name_at_the_end_is_cut_out():
    match = hit("ช่วยบอกเวลาหน่อยยูกะ")
    assert match and match.remainder == "ช่วยบอกเวลาหน่อย"


def test_a_stray_leftover_is_dropped():
    # Fewer than three characters left is a misheard syllable, not a request.
    match = hit("ยูกะ โ")
    assert match and match.remainder == ""


def test_bare_name_has_no_remainder():
    assert hit("ยูกะ").remainder == ""


def test_name_in_the_middle_counts_only_with_anywhere():
    text = "ฉันไปซื้อของที่ตลาดมาแล้วนะ ยูกะ เปิดเพลงให้หน่อย แล้วก็ไปต่อ"
    assert detect(text, WORDS, threshold=80, anywhere=True)
    assert not detect(text, WORDS, threshold=80, anywhere=False)


def test_empty_input():
    assert not detect("", WORDS)
    assert not detect("ยูกะ", [])


def test_normalize_folds_tone_marks_case_and_kana():
    assert normalize("ยูก้า") == normalize("ยูกา")
    assert normalize("YUUKA") == "yuuka"
    assert normalize("ユーカ") == normalize("ゆうか") == "ゆうか"
