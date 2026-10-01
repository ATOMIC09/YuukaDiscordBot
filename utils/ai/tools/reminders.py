"""
utils/ai/tools/reminders.py
Set a reminder or a voice-join alert. Both end the turn: the timer or listener
lives in `utils.ai.scheduler` and costs no LLM requests while it waits.
"""

from __future__ import annotations

from langchain_core.tools import tool

from utils.ai.context import Ctx, YuukaContext
from utils.ai.scheduler import ReminderScheduler
from utils.ai.tools.resolve import resolve_member
from utils.embeds import success_embed


def scheduler_for(ctx: YuukaContext) -> ReminderScheduler | None:
    chat_cog = ctx.bot.get_cog("AI Chat")
    return getattr(chat_cog, "scheduler", None)


@tool(return_direct=True)
async def remind_me(minutes: int, text: str, ctx: Ctx) -> str:
    """Remind the requester about something after some minutes (1 to 1440).

    `text` is what to remind them of, e.g. "เข้าประชุม".
    """
    scheduler = scheduler_for(ctx)
    if ctx.before_action is not None:
        await ctx.before_action("ได้ค่ะ เดี๋ยวหนูเตือนให้นะคะ" if ctx.voice else "")

    pending = scheduler.add_reminder(ctx.requester, ctx.channel, minutes, text)
    await scheduler.attach_cancel_button(
        pending,
        success_embed("⏰ ตั้งเตือนให้แล้วค่ะ", f"อีก **{minutes} นาที** หนูจะเตือนเรื่อง: {text}"),
    )
    return "Reminder set."


@tool(return_direct=True)
async def notify_when_joins_voice(member: str, ctx: Ctx, minutes: int = 60) -> str:
    """Tell the requester when a member joins a voice channel, watching for up to `minutes` (1 to 1440)."""
    scheduler = scheduler_for(ctx)
    target = resolve_member(ctx, member)
    if ctx.before_action is not None:
        await ctx.before_action(f"ได้ค่ะ ถ้า {target.display_name} เข้ามาหนูจะบอกนะคะ" if ctx.voice else "")

    pending = scheduler.add_voice_watch(ctx.requester, ctx.channel, target, minutes)
    await scheduler.attach_cancel_button(
        pending,
        success_embed(
            "🔔 รับทราบค่ะ",
            f"หนูจะบอกเซนเซย์เมื่อ {target.display_name} เข้าห้องเสียง (เฝ้าดูนาน {minutes} นาที)",
        ),
    )
    return "Watch set."


TOOLS = [remind_me, notify_when_joins_voice]
STATUS: dict = {}
