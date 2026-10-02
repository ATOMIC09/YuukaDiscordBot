"""
utils/ai/progress.py
A live "what she is doing" embed for a turn that takes a while.

A turn can run for tens of seconds with nothing on screen: the model thinks, calls a
tool, thinks again, and a request with several songs makes several calls. Nobody can
tell whether she understood, so they ask again and get it twice. This embed shows the
current step and the plan as a checklist, and is deleted when the turn ends.

It feeds on the agent's events (`utils.ai.agent.run_agent`): `thinking`, `plan` and
`step`. Every other event is ignored. It appears only for a turn that is slow enough
to need it: after `SHOW_AFTER_S`, or at once for a plan of several steps. A quick
one-line answer never shows it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import discord

from bot.logger import logger
from utils.ai.tools.labels import describe_call
from utils.embeds import COLOR_INFO

SHOW_AFTER_S = 3.0
# A plan this long is a long task however fast the first step is.
SHOW_PLAN_AT = 2

_ICONS = {"waiting": "⏳", "running": "🔄", "ok": "✅", "failed": "❌", "skipped": "➖"}


class TurnProgress:
    def __init__(self, channel: discord.abc.Messageable) -> None:
        self._channel = channel
        self._started = time.time()
        self._round = (1, 1)
        self._thinking = True
        self._steps: list[tuple[str, str]] = []  # (label, state)
        self._base = 0  # where the current plan starts in `_steps`
        self._message: discord.Message | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._visible = False
        self._finished = False
        self._timer = asyncio.create_task(self._show_later())

    def feed(self, event: str, payload: Any) -> None:
        """Take one agent event. Never blocks the turn: drawing happens in the background."""
        if event == "thinking":
            self._round, self._thinking = payload, True
        elif event == "plan":
            self._thinking = False
            self._base = len(self._steps)
            self._steps += [(describe_call(c["name"], c["args"]), "waiting") for c in payload]
            if len(payload) >= SHOW_PLAN_AT:
                self._visible = True
        elif event == "step":
            index, state = payload
            if 0 <= self._base + index < len(self._steps):
                label, _ = self._steps[self._base + index]
                self._steps[self._base + index] = (label, state)
        else:
            return
        if self._visible:
            self._draw()

    async def finish(self) -> None:
        """The turn is over: stop the timer and take the embed down."""
        self._finished = True
        self._timer.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        async with self._lock:
            if self._message is not None:
                try:
                    await self._message.delete()
                except discord.HTTPException:
                    pass
                self._message = None

    # ── drawing ───────────────────────────────────────────────────────────

    async def _show_later(self) -> None:
        try:
            await asyncio.sleep(SHOW_AFTER_S)
        except asyncio.CancelledError:
            return
        self._visible = True
        self._draw()

    def _draw(self) -> None:
        task = asyncio.create_task(self._render())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _embed(self) -> discord.Embed:
        lines = [f"{_ICONS[state]} {label}" for label, state in self._steps]
        if self._thinking:
            number, limit = self._round
            lines.append("💭 กำลังคิด" + (f" (รอบที่ {number}/{limit})" if number > 1 else "") + "...")
        embed = discord.Embed(
            title="🧠 หนูกำลังทำงานให้อยู่ค่ะ",
            description="\n".join(lines) or "💭 กำลังคิด...",
            color=COLOR_INFO,
        )
        embed.set_footer(text="รอสักครู่นะคะ เซนเซย์ ไม่ต้องสั่งซ้ำน้า (・`ω´・)")
        return embed

    async def _render(self) -> None:
        async with self._lock:
            if self._finished:
                return
            embed = self._embed()  # the state now, not when this render was queued
            try:
                if self._message is None:
                    self._message = await self._channel.send(embed=embed)
                else:
                    await self._message.edit(embed=embed)
            except discord.HTTPException as exc:
                logger.warning(f"[Progress] Could not draw the progress embed: {exc}")
