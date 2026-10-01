"""
utils/ai/confirm.py
A confirmation step for actions that affect other people.

Yuuka only proposes these (kick someone, start a disconnect timer). Nothing
happens until the requester presses the button, and pressing it costs no LLM
request: the stored action simply runs.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import discord

from bot.logger import logger
from utils.embeds import error_embed, info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning

_TIMEOUT_S = 60


class ConfirmActionView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: discord.Bot,
        guild: discord.Guild,
        requester: discord.Member,
        action: Callable[[], Awaitable[str]],
        check: Callable[[], None] | None = None,
    ) -> None:
        """`action` does the work and returns a one-line result; it may raise
        UserError/UserWarning to refuse. `check` is run again on confirm, since
        the requester's permissions may have changed in the meantime."""
        super().__init__(timeout=_TIMEOUT_S)
        self.bot = bot
        self.guild = guild
        self.requester = requester
        self.action = action
        self.check = check
        self.message: discord.Message | None = None
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester.id:
            return True
        await interaction.response.send_message(
            f"ปุ่มนี้ให้ {self.requester.display_name} กดได้คนเดียวนะคะ (´-ω-`)", ephemeral=True
        )
        return False

    def _close(self) -> None:
        self.done = True
        for child in self.children:
            child.disabled = True
        self.stop()

    @discord.ui.button(label="ยืนยัน", style=discord.ButtonStyle.success)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if self.done:
            return
        self._close()
        await interaction.response.defer()

        line = ""
        try:
            if self.check:
                self.check()
            line = await self.action()
            embed = success_embed("เรียบร้อยค่ะ", line)
        except UserError as exc:
            embed = error_embed(exc.title, exc.description)
        except UserWarning as exc:
            embed = warning_embed(exc.title, exc.description)
        except Exception as exc:
            logger.exception(f"[AI Confirm] Action failed: {exc}")
            embed = error_embed("เกิดข้อผิดพลาด", "ทำไม่สำเร็จค่ะ เซนเซย์ลองอีกรอบนะคะ")

        await interaction.edit_original_response(embed=embed, view=self)

        voice_cog = self.bot.get_cog("AI Voice Chat")
        if line and voice_cog is not None:
            await voice_cog.announce(self.guild.id, line)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if self.done:
            return
        self._close()
        await interaction.response.edit_message(
            embed=warning_embed("ยกเลิกแล้วค่ะ", "ไม่ทำอะไรนะคะ (´-ω-`)"), view=self
        )

    async def on_timeout(self) -> None:
        if self.done:
            return
        self._close()
        if self.message is not None:
            try:
                await self.message.edit(
                    embed=info_embed("หมดเวลาแล้วค่ะ", "เซนเซย์ไม่ได้กดยืนยัน หนูเลยไม่ทำอะไรนะคะ"),
                    view=self,
                )
            except discord.HTTPException as exc:
                logger.warning(f"[AI Confirm] Could not mark the confirmation as expired: {exc}")
