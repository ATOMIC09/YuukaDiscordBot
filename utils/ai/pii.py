"""
utils/ai/pii.py
Personal data in text other people wrote (a channel she reads, a web page) is hidden before the
text goes to the model provider: emails, Thai phone numbers, Thai national IDs and card numbers.

The requester can see those numbers in Discord anyway; this is about the provider. Links and
mentions are left alone, since a Discord ID is 17-19 digits and a quarter of a percent of them would
otherwise pass for a card number.
"""

from __future__ import annotations

import re
from collections import Counter

from bot.config import config
from bot.logger import logger

# Links and <#123> / <@123> / <https://…> are never touched.
_PROTECTED = r"(?P<keep>https?://[^\s<>]+|<[^<>\s]+>)"
_EMAIL = r"(?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)"
# Not part of a longer run of digits, however it is spaced or dashed.
_START = r"(?<!\d)(?<!\d[ -])"
_END = r"(?![ -]?\d)"
# 0 or +66, then the first digit of the number, then 7-8 more: 9-digit landlines, 10-digit mobiles.
_PHONE = rf"(?P<phone>{_START}(?:\+66[ -]?|0)[2-9](?:[ -]?\d){{7,8}}{_END})"
_THAI_ID = rf"(?P<id>{_START}[1-8](?:[ -]?\d){{12}}{_END})"
_CARD = rf"(?P<card>{_START}\d(?:[ -]?\d){{14,18}}{_END})"

_PATTERN = re.compile("|".join((_PROTECTED, _EMAIL, _PHONE, _THAI_ID, _CARD)))

PLACEHOLDERS = {"email": "[email]", "phone": "[phone]", "id": "[thai-id]", "card": "[card]"}


def thai_id_valid(digits: str) -> bool:
    """The 13th digit of a Thai national ID is a checksum of the first twelve."""
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
    return (11 - total % 11) % 10 == int(digits[12])


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def hide(text: str, where: str) -> str:
    """`redact`, when AI_REDACT_PII is on, with a log line saying how many (never what) were hidden
    in `where`. For text that goes into her history without passing through a tool."""
    if not config.ai_redact_pii:
        return text
    counts: Counter = Counter()
    text = redact(text, counts)
    if counts:
        logger.info(f"[PII] Hid {sum(counts.values())} item(s) in {where}: {dict(counts)}")
    return text


def redact(text: str, counts: Counter | None = None) -> str:
    """`text` with personal data replaced by typed placeholders. `counts` collects how many of each
    kind (never what they were): it is for a log line."""

    def replace(match: re.Match) -> str:
        kind = match.lastgroup
        value = match.group()
        if kind == "keep":
            return value
        digits = re.sub(r"\D", "", value)
        if kind == "id" and not thai_id_valid(digits):
            return value
        if kind == "card" and not luhn_valid(digits):
            return value
        if counts is not None:
            counts[kind] += 1
        return PLACEHOLDERS[kind]

    return _PATTERN.sub(replace, text)
