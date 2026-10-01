"""
utils/ai/tools/wait.py
A pause between calls in one reply: "play it, wait 10 seconds, then skip".

The model is not called while it waits. The turn stays open, though, so in
/ai voice she cannot take a new request until it ends; longer delays belong to
`remind_me`, which waits in the scheduler instead.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool

from utils.errors import UserWarning

MAX_SECONDS = 60
# "รอสักครู่", "รอแป๊บ", "a moment": a delay with no number. Fixed, so the same words
# always mean the same wait instead of whatever number the model picks.
DEFAULT_SECONDS = 10


@tool
async def wait(seconds: int | None = None) -> str:
    """Pause for some seconds (1 to 60) before the next call in the same reply.

    Use it between calls when the user asks for a delay, e.g. queue a song,
    wait 10 seconds, then skip.

    `seconds` must be a number the user actually said ("รอ 5 วิ" -> 5). Words
    without a number ("สักครู่", "สักแป๊บ", "แปปนึง", "in a moment") are not a
    number: leave `seconds` out entirely and never guess one.
    """
    seconds = seconds or DEFAULT_SECONDS
    if not 1 <= seconds <= MAX_SECONDS:
        raise UserWarning("รอนานขนาดนั้นไม่ได้ค่ะ", f"หนูรอได้ทีละ 1 ถึง {MAX_SECONDS} วินาทีนะคะ")
    await asyncio.sleep(seconds)
    return f"Waited {seconds} seconds."


def _status(args: dict) -> str:
    seconds = args.get("seconds") or DEFAULT_SECONDS
    return f"<a:AppleLoadingGIF:1052465926487953428> รอ {seconds} วินาทีนะคะ..."


TOOLS = [wait]
STATUS = {"wait": _status}
