"""
utils/ai/scheduler.py
Reminders and voice-join alerts that cost no LLM tokens while they wait.

Creating one is a normal agent turn (the model emits one tool call). After that
it is just an asyncio timer or a Discord event listener, and when it fires it
posts a fixed template: nothing here ever calls the model.

Everything lives in memory. The bot runs in a stateless container, so pending
items are lost on restart; that is accepted.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

import discord

from bot.logger import logger
from utils.embeds import info_embed, warning_embed
from utils.errors import UserWarning

MAX_PENDING_PER_USER = 5
MIN_MINUTES = 1
MAX_MINUTES = 24 * 60


@dataclass
class Pending:
    id: int
    kind: str  # "reminder" or "watch"
    user: discord.Member
    channel: discord.abc.Messageable
    text: str
    target: discord.Member | None = None
    task: asyncio.Task | None = None
    message: discord.Message | None = None
    view: discord.ui.View | None = None


class CancelView(discord.ui.View):
    """One button, usable only by the person who set the reminder."""

    def __init__(self, scheduler: ReminderScheduler, pending: Pending) -> None:
        super().__init__(timeout=None)
        self.scheduler = scheduler
        self.pending = pending

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.pending.user.id:
            return True
        await interaction.response.send_message(
            f"ปุ่มนี้ให้ {self.pending.user.display_name} กดได้คนเดียวนะคะ (´-ω-`)", ephemeral=True
        )
        return False

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        self.scheduler.cancel(self.pending)
        self.stop()
        await interaction.response.edit_message(
            embed=warning_embed("ยกเลิกแล้วค่ะ", "หนูลบการแจ้งเตือนนี้ให้แล้วนะคะ (´-ω-`)"), view=None
        )


class ReminderScheduler:
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.pending: dict[int, list[Pending]] = {}
        self._ids = itertools.count(1)

    # ── creating ──────────────────────────────────────────────────────────

    def _check(self, user: discord.Member, minutes: int) -> None:
        if not MIN_MINUTES <= minutes <= MAX_MINUTES:
            raise UserWarning("เวลาไม่ถูกต้องค่ะ", "ตั้งได้ตั้งแต่ 1 นาทีถึง 24 ชั่วโมงนะคะ")
        if len(self.pending.get(user.id, [])) >= MAX_PENDING_PER_USER:
            raise UserWarning(
                "ตั้งเตือนเต็มแล้วค่ะ",
                f"เซนเซย์มีการแจ้งเตือนค้างอยู่ {MAX_PENDING_PER_USER} อันแล้ว ยกเลิกบางอันก่อนนะคะ",
            )

    def _add(self, pending: Pending, minutes: int) -> Pending:
        self.pending.setdefault(pending.user.id, []).append(pending)
        pending.task = asyncio.create_task(
            self._wait(pending, minutes * 60), name=f"ai_pending_{pending.id}"
        )
        return pending

    def add_reminder(
        self, user: discord.Member, channel: discord.abc.Messageable, minutes: int, text: str
    ) -> Pending:
        self._check(user, minutes)
        return self._add(Pending(next(self._ids), "reminder", user, channel, text), minutes)

    def add_voice_watch(
        self,
        user: discord.Member,
        channel: discord.abc.Messageable,
        target: discord.Member,
        minutes: int,
    ) -> Pending:
        self._check(user, minutes)
        # A channel the watcher cannot see counts as not in voice, as it does
        # in their own Discord client.
        if target.voice and target.voice.channel and target.voice.channel.permissions_for(user).view_channel:
            raise UserWarning(
                "เขาอยู่ในห้องเสียงแล้วค่ะ",
                f"{target.display_name} อยู่ในช่อง {target.voice.channel.name} อยู่แล้วนะคะ",
            )
        return self._add(
            Pending(next(self._ids), "watch", user, channel, target.display_name, target), minutes
        )

    async def attach_cancel_button(self, pending: Pending, embed: discord.Embed) -> None:
        """Post the confirmation for `pending` with its cancel button."""
        pending.view = CancelView(self, pending)
        pending.message = await pending.channel.send(embed=embed, view=pending.view)

    # ── ending ────────────────────────────────────────────────────────────

    def _remove(self, pending: Pending) -> None:
        items = self.pending.get(pending.user.id, [])
        if pending in items:
            items.remove(pending)
        if not items:
            self.pending.pop(pending.user.id, None)

    async def _retire_button(self, pending: Pending) -> None:
        if pending.view is not None:
            pending.view.stop()
        if pending.message is not None:
            try:
                await pending.message.edit(view=None)
            except discord.HTTPException:
                pass

    def cancel(self, pending: Pending) -> None:
        if pending.task and not pending.task.done():
            pending.task.cancel()
        self._remove(pending)

    def cancel_all(self) -> None:
        for items in list(self.pending.values()):
            for pending in list(items):
                self.cancel(pending)

    async def _wait(self, pending: Pending, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        self._remove(pending)
        await self._retire_button(pending)
        if pending.kind == "reminder":
            await self._fire(
                pending,
                info_embed("⏰ แจ้งเตือนค่ะเซนเซย์", pending.text),
                f"เซนเซย์คะ ถึงเวลาแล้วนะคะ {pending.text}",
            )
        # An unmatched voice watch simply runs out.

    async def on_voice_join(self, member: discord.Member, channel: discord.VoiceChannel) -> None:
        """Called when someone enters a voice channel; fires any watch waiting for them."""
        for items in list(self.pending.values()):
            for pending in list(items):
                if pending.kind != "watch" or pending.target.id != member.id:
                    continue
                if pending.user.guild.id != member.guild.id:
                    continue
                if not channel.permissions_for(pending.user).view_channel:
                    continue  # never reveal a room the watcher cannot see; keep waiting
                if pending.task and not pending.task.done():
                    pending.task.cancel()
                self._remove(pending)
                await self._retire_button(pending)
                await self._fire(
                    pending,
                    info_embed("🔔 มีคนเข้าห้องเสียงแล้วค่ะ", f"{member.display_name} เข้าห้อง {channel.mention} แล้วค่ะ"),
                    f"{member.display_name} เข้าห้อง {channel.name} แล้วค่ะ",
                )

    async def _fire(self, pending: Pending, embed: discord.Embed, spoken: str) -> None:
        logger.info(f"[AI Scheduler] Firing {pending.kind} #{pending.id} for {pending.user}")
        try:
            await pending.channel.send(content=pending.user.mention, embed=embed)
        except discord.HTTPException as exc:
            logger.warning(f"[AI Scheduler] Could not post {pending.kind} #{pending.id}: {exc}")

        voice_cog = self.bot.get_cog("AI Voice Chat")
        if voice_cog is not None:
            await voice_cog.announce(pending.user.guild.id, spoken)
