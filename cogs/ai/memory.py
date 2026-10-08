"""
cogs/ai/memory.py
/memory setup, and the store behind Yuuka's server memory: the notes she keeps for a server.

The notes live in a hidden channel of the server (`utils.ai.memory`). This cog owns the store,
keeps its RAM copy in step with that channel, and holds the commands. The agent's tools reach the
store through `bot.get_cog("AI Memory").store`.

Nothing here logs a note's text, and the commands take no free text, so the command log never
receives one either.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from utils.ai.memory import CHANNEL_NAME, MARKER, MemoryStore, is_memory_channel
from utils.embeds import info_embed, success_embed
from utils.errors import UserError, UserWarning

_TOPIC = f"{MARKER} สมุดความจำของ Yuuka: ลบข้อความ = ให้หนูลืมโน้ตนั้น ห้ามเปิดให้คนทั่วไปเห็น"

_INTRO = (
    "ช่องนี้คือสมุดจดของหนูค่ะ เซนเซย์ (๑>◡<๑)\n\n"
    "• หนูจดหนึ่งเรื่องต่อหนึ่งข้อความ และจดเฉพาะตอนที่มีคนขอให้จำเท่านั้นนะคะ\n"
    "• ลบข้อความไหน หนูก็ลืมเรื่องนั้นทันที ลบทั้งช่องคือหนูลืมทุกอย่างค่ะ\n"
    "• ไม่มีอะไรถูกเก็บไว้ในเครื่องที่หนูทำงานอยู่เลย ทุกอย่างอยู่ที่ช่องนี้ที่เดียวค่ะ\n"
    "• หนูไม่เอาเรื่องจากช่องที่คนในช่องนี้อ่านไม่ได้มาจดที่นี่ และจะไม่เอาเรื่องจากช่องไหน "
    "ไปเล่าในที่ที่คนอ่านช่องนั้นไม่ได้ค่ะ\n\n"
    "ช่วยให้เห็นแค่แอดมินนะคะ ถ้าเปิดให้คนอื่นเห็น หนูจะจดเรื่องจากช่องส่วนตัวมาเก็บที่นี่ไม่ได้แล้วค่ะ (・`ω´・)"
)

def _guild_of(ctx: discord.ApplicationContext) -> discord.Guild:
    if ctx.guild is None:
        raise UserWarning("ใช้ในเซิร์ฟเวอร์เท่านั้นค่ะ", "คำสั่งนี้ใช้ในแชทส่วนตัวไม่ได้นะคะ ต้องไปใช้ในเซิร์ฟเวอร์น้า (´・ω・)")
    return ctx.guild


class MemoryCog(commands.Cog, name="AI Memory"):
    """The server's memory: the store, the commands, and the listeners that keep them honest."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.store = MemoryStore(bot)
        self._setting_up: set[int] = set()

    memory = discord.SlashCommandGroup("memory", "📒 ระบบความจำของ AI ในเซิร์ฟเวอร์นี้")

    # ── Keeping the RAM copy true ─────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id:
            self.store.on_deleted(payload.guild_id, payload.channel_id, [payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if payload.guild_id:
            self.store.on_deleted(payload.guild_id, payload.channel_id, payload.message_ids)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        self.store.drop_if_channel(channel.guild.id, channel.id)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if is_memory_channel(before) and not is_memory_channel(after):
            self.store.drop_if_channel(after.guild.id, after.id)  # the marker was taken off
        self.store.clear_audience()  # who can see a channel may have changed

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        self.store.clear_audience()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        self.store.clear_audience()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles != after.roles:
            self.store.clear_audience()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self.store.forget_guild(guild.id)

    # ── /memory setup ─────────────────────────────────────────────────────

    @memory.command(name="setup", description="🛠️ สร้างช่องความจำลับให้ AI จดเรื่องของเซิร์ฟเวอร์ (ต้องมีสิทธิ์จัดการเซิร์ฟเวอร์)")
    async def memory_setup(self, ctx: discord.ApplicationContext) -> None:
        guild = _guild_of(ctx)
        if not ctx.author.guild_permissions.manage_guild:
            raise UserWarning("ต้องเป็นแอดมินนะคะ", "คำสั่งนี้ใช้ได้เฉพาะคนที่มีสิทธิ์จัดการเซิร์ฟเวอร์ค่ะ (´-ω-`)")
        existing = self.store.channel_for(guild)
        if existing is not None or guild.id in self._setting_up:
            where = f" คือ {existing.mention}" if existing else ""
            raise UserWarning("มีสมุดความจำอยู่แล้วค่ะ", f"เซิร์ฟเวอร์นี้ตั้งสมุดความจำไว้แล้วนะคะ{where}")
        if not guild.me.guild_permissions.manage_channels:
            raise UserError(
                "หนูสร้างช่องไม่ได้ค่ะ",
                "หนูต้องมีสิทธิ์ **จัดการช่อง** ก่อนนะคะ ให้สิทธิ์แล้วลอง `/memory setup` อีกครั้งน้า",
            )

        self._setting_up.add(guild.id)
        try:
            await ctx.defer()
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, embed_links=True, read_message_history=True
                ),
            }
            try:
                channel = await guild.create_text_channel(
                    CHANNEL_NAME, overwrites=overwrites, topic=_TOPIC, reason=f"/memory setup โดย {ctx.author}"
                )
                await channel.send(embed=info_embed("📒 สมุดความจำของ Yuuka", _INTRO))
            except discord.Forbidden:
                raise UserError("หนูสร้างช่องไม่ได้ค่ะ", "Discord ไม่อนุญาตให้หนูสร้างช่องนี้ ลองตรวจสิทธิ์ของหนูอีกทีนะคะ")
        finally:
            self._setting_up.discard(guild.id)

        logger.info(f"[Memory] Guild {guild.id}: memory channel created")
        note = ""
        if not ctx.author.guild_permissions.administrator:
            note = "\n\nเซนเซย์ไม่ได้เป็นแอดมิน เลยอาจมองไม่เห็นช่องนี้ค่ะ ให้แอดมินดูแทนได้นะคะ"
        await ctx.respond(embed=success_embed(
            "📒 สร้างสมุดความจำแล้วค่ะ",
            f"หนูสร้างช่อง {channel.mention} ไว้จดเรื่องที่ทุกคนขอให้จำค่ะ (เห็นเฉพาะแอดมิน)\n"
            "ลองบอกหนูดูนะคะ เช่น *«@Yuuka จำไว้นะว่าต้องเล่น Minecraft ทุกคืนวันเสาร์»*\n"
            "ใครอยากดูหรือลบเรื่องของตัวเอง ใช้ `/memory me` ได้เลยค่ะ"
            f"{note}",
        ))


def setup(bot: discord.Bot) -> None:
    bot.add_cog(MemoryCog(bot))
