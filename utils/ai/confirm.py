"""
utils/ai/confirm.py
A confirmation step for actions that affect other people.

Yuuka only proposes these (kick someone, start a disconnect timer). Nothing
happens until the requester presses the button, and pressing it costs no LLM
request: the stored action simply runs.

In a voice session the requester can also answer out loud (`spoken_decision`);
the voice cog hands that to `decide_by_voice`. Still no LLM request.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

import discord

from bot.logger import logger
from utils import ai_actions
from utils.embeds import error_embed, info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning

_TIMEOUT_S = 60

# A spoken answer is a short utterance. Anything longer is conversation that merely
# contains one of these words ("ไม่รู้สิ ว่าจะเปิดเพลงอะไรดี"), so it is not an answer.
_ANSWER_MAX_CHARS = 30
_YES = re.compile(
    r"ยืนยัน|ตกลง|โอเค|เอาเลย|ทำเลย|จัดไป|ได้เลย|ใช่|(?<![a-z])(?:ok|okay|yes|yep|confirm)(?![a-z])"
)
_NO = re.compile(
    r"ยกเลิก|ไม่|อย่า|หยุด|เปลี่ยนใจ|(?<![a-z])(?:no|nope|cancel|stop)(?![a-z])"
)


def spoken_decision(text: str) -> bool | None:
    """True to confirm, False to cancel, None when `text` is not an answer.

    A "no" word wins over a "yes" word, so "ไม่ใช่" and "ไม่ได้" cancel: when it is
    unclear, nothing should happen to anybody."""
    text = re.sub(r"[\s.,!?。、…~]+", " ", text.lower()).strip()
    if not text or len(text) > _ANSWER_MAX_CHARS:
        return None
    if _NO.search(text):
        return False
    if _YES.search(text):
        return True
    return None


class ConfirmActionView(discord.ui.View):
    def __init__(
        self,
        *,
        bot: discord.Bot,
        guild: discord.Guild,
        requester: discord.Member,
        action: Callable[[], Awaitable[str]],
        check: Callable[[], None] | None = None,
        command: str = "",
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
        self.command = command  # for the command log, e.g. "/kick @name"
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

    async def _perform(self) -> tuple[discord.Embed, str, str]:
        """Run the action. Returns the embed to show, the result line when it worked,
        and the reason when it did not."""
        try:
            if self.check:
                self.check()
            line = await self.action()
            await self._log(True, line)
            return success_embed("เรียบร้อยค่ะ", line), line, ""
        except UserError as exc:
            await self._log(False, exc.description)
            return error_embed(exc.title, exc.description), "", exc.description
        except UserWarning as exc:
            await self._log(False, exc.description)
            return warning_embed(exc.title, exc.description), "", exc.description
        except Exception as exc:
            logger.exception(f"[AI Confirm] Action failed: {exc}")
            reason = "ทำไม่สำเร็จค่ะ เซนเซย์ลองอีกรอบนะคะ"
            await self._log(False, reason)
            return error_embed("เกิดข้อผิดพลาด", reason), "", reason

    async def _log(self, ok: bool, detail: str) -> None:
        """The command log gets it too: it was confirmed, so it was a command someone ran."""
        if self.command:
            await ai_actions.log_command(
                self.bot,
                guild=self.guild,
                channel=self.message.channel if self.message is not None else None,
                member=self.requester,
                command=self.command,
                ok=ok,
                detail=detail,
                jump_url=self.message.jump_url if self.message is not None else None,
            )

    async def _announce(self, text: str) -> None:
        voice_cog = self.bot.get_cog("AI Voice Chat")
        if text and voice_cog is not None:
            await voice_cog.announce(self.guild.id, text)

    async def decide_by_voice(self, confirmed: bool) -> None:
        """The requester said yes or no out loud: same outcome as the button, and the
        answer is spoken back because they may not be looking at the chat."""
        if self.done:
            return
        self._close()
        if confirmed:
            embed, line, reason = await self._perform()
            spoken = line or reason
        else:
            embed = warning_embed("ยกเลิกแล้วค่ะ", "ไม่ทำอะไรนะคะ (´-ω-`)")
            spoken = "ยกเลิกแล้วค่ะ"

        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException as exc:
                logger.warning(f"[AI Confirm] Could not update the confirmation: {exc}")
        await self._announce(spoken)

    @discord.ui.button(label="ยืนยัน", style=discord.ButtonStyle.success)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if self.done:
            return
        self._close()
        await interaction.response.defer()

        embed, line, _ = await self._perform()
        await interaction.edit_original_response(embed=embed, view=self)
        await self._announce(line)

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
        # In a call the requester may not be watching the chat; the chime that opened the
        # spoken yes/no gets this as its close.
        await self._announce("หมดเวลายืนยันแล้วค่ะ")
