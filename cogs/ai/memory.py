"""
cogs/ai/memory.py
/memory: set up, see, forget and opt out of the notes Yuuka keeps for a server.

The notes live in a hidden channel of the server (`utils.ai.memory`). This cog owns the store,
keeps its RAM copy in step with that channel, and holds the commands. The agent's tools reach the
store through `bot.get_cog("AI Memory").store`.

Nothing here logs a note's text, and the commands take no free text, so the command log never
receives one either.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import discord
from discord.ext import commands

from bot.logger import logger
from utils.ai.memory import CHANNEL_NAME, MARKER, MemoryStore, Note, is_memory_channel
from utils.ai.tools.resolve import can_view
from utils.embeds import info_embed, success_embed, warning_embed
from utils.errors import UserError, UserWarning

_TOPIC = f"{MARKER} สมุดความจำของ Yuuka: ลบข้อความ = ให้หนูลืมโน้ตนั้น ห้ามเปิดให้คนทั่วไปเห็น"

_INTRO = (
    "ช่องนี้คือสมุดจดของหนูค่ะ เซนเซย์ (๑>◡<๑)\n\n"
    "• หนูจดหนึ่งเรื่องต่อหนึ่งข้อความ และจดเฉพาะตอนที่มีคนขอให้จำ หรือกดปุ่ม “จำไว้” ตอนที่หนูถามเท่านั้นนะคะ\n"
    "• ลบข้อความไหน หนูก็ลืมเรื่องนั้นทันที ลบทั้งช่องคือหนูลืมทุกอย่างค่ะ\n"
    "• ไม่มีอะไรถูกเก็บไว้ในเครื่องที่หนูทำงานอยู่เลย ทุกอย่างอยู่ที่ช่องนี้ที่เดียวค่ะ\n"
    "• หนูไม่เอาเรื่องจากช่องที่คนในช่องนี้อ่านไม่ได้มาจดที่นี่ และจะไม่เอาเรื่องจากช่องไหน "
    "ไปเล่าในที่ที่คนอ่านช่องนั้นไม่ได้ค่ะ\n\n"
    "ช่วยให้เห็นแค่แอดมินนะคะ ถ้าเปิดให้คนอื่นเห็น หนูจะจดเรื่องจากช่องส่วนตัวมาเก็บที่นี่ไม่ได้แล้วค่ะ (・`ω´・)"
)

_PAGE = 15  # notes listed by /memory me


def _clip(text: str, size: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1] + "…"


def _guild_of(ctx: discord.ApplicationContext) -> discord.Guild:
    if ctx.guild is None:
        raise UserWarning("ใช้ในเซิร์ฟเวอร์เท่านั้นค่ะ", "คำสั่งนี้ใช้ในแชทส่วนตัวไม่ได้นะคะ ต้องไปใช้ในเซิร์ฟเวอร์น้า (´・ω・)")
    return ctx.guild


async def _can_open(member: discord.Member, channel) -> bool:
    """Whether `member` can open `channel` and read its history, as they would in their own client."""
    if channel is None:
        return False
    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        return await can_view(member, channel) and channel.permissions_for(member).read_message_history
    perms = channel.permissions_for(member)
    return perms.view_channel and perms.read_message_history


class _Confirm(discord.ui.View):
    """Yes or no under an ephemeral message, for something that deletes the member's own notes."""

    def __init__(self, run: Callable[[], Awaitable[discord.Embed]]) -> None:
        super().__init__(timeout=60)
        self.run = run
        self.used = False

    @discord.ui.button(label="ยืนยัน", style=discord.ButtonStyle.danger)
    async def yes(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        if self.used:
            return
        self.used = True
        self.stop()
        await interaction.response.defer()
        try:
            embed = await self.run()
        except UserWarning as exc:
            embed = warning_embed(exc.title, exc.description)
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def no(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        self.used = True
        self.stop()
        await interaction.response.edit_message(
            embed=info_embed("ไม่ทำอะไรค่ะ", "หนูยังจำทุกอย่างไว้เหมือนเดิมนะคะ (´-ω-`)"), view=None
        )


class _ForgetMenu(discord.ui.View):
    """Pick notes to forget, or forget everything about the member."""

    def __init__(
        self, store: MemoryStore, guild: discord.Guild, member: discord.Member, notes: list[Note], total: int
    ) -> None:
        super().__init__(timeout=120)
        self.store = store
        self.guild = guild
        self.member = member
        self.total = total
        self.offered = {str(n.id): n for n in notes}
        self.chosen: list[str] = []
        self.select: discord.ui.Select | None = None
        if notes:
            self.select = discord.ui.Select(
                placeholder="เลือกเรื่องที่ให้หนูลืม",
                min_values=1,
                max_values=len(notes),
                row=0,
                options=[
                    discord.SelectOption(label=_clip(n.text, 95), value=str(n.id), description=f"{n.created:%Y-%m-%d}")
                    for n in notes
                ],
            )
            self.select.callback = self._picked
            self.add_item(self.select)
        else:
            self.remove_item(self.submit)  # nothing to pick from, only "forget everything"

    async def _picked(self, interaction: discord.Interaction) -> None:
        """Only remembers the choice. Discord calls a select back the moment its menu closes, and
        clicking anywhere closes it, so deleting here would act on a stray click."""
        self.chosen = [v for v in (self.select.values or []) if v in self.offered]
        for option in self.select.options:
            option.default = option.value in self.chosen
        self.submit.disabled = not self.chosen
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="ลืมเรื่องที่เลือก", style=discord.ButtonStyle.success, disabled=True, row=1)
    async def submit(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            gone = 0
            for value in self.chosen:
                gone += await self.store.delete(self.guild, self.offered[value].id)
            embed = success_embed("ลืมแล้วค่ะ", f"หนูลืมไป {gone} เรื่องแล้วนะคะ (´-ω-`)")
        except UserWarning as exc:
            embed = warning_embed(exc.title, exc.description)
        self.stop()
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="ลืมทุกอย่างที่เกี่ยวกับฉัน", style=discord.ButtonStyle.danger, row=1)
    async def forget_all(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        async def wipe() -> discord.Embed:
            gone = await self.store.forget_member(self.guild, self.member.id)
            return success_embed("ลืมแล้วค่ะ", f"หนูลืมไป {gone} เรื่องแล้วนะคะ (´-ω-`)")

        self.stop()
        await interaction.response.edit_message(
            embed=warning_embed(
                "ลบทั้งหมดเลยนะคะ?",
                f"หนูจะลืมทั้ง {self.total} เรื่องที่เกี่ยวกับเซนเซย์หรือเซนเซย์เป็นคนบอก "
                "รวมถึงเรื่องจากช่องที่เซนเซย์อ่านไม่ได้ด้วยค่ะ",
            ),
            view=_Confirm(wipe),
        )


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

    # ── /memory me, forget ────────────────────────────────────────────────

    async def _mine(self, guild: discord.Guild, member: discord.Member) -> tuple[list[Note], int]:
        """A member's notes whose channel they can read, and how many more they cannot."""
        await self.store.ensure_loaded(guild)
        readable: list[Note] = []
        hidden = 0
        for note in self.store.about_or_by(guild.id, member.id):
            if await _can_open(member, guild.get_channel_or_thread(note.source_id)):
                readable.append(note)
            else:
                hidden += 1
        return readable, hidden

    @memory.command(name="me", description="📖 ดูสิ่งที่ AI จำเกี่ยวกับตัวเองไว้ (เห็นคนเดียว)")
    async def memory_me(self, ctx: discord.ApplicationContext) -> None:
        guild = _guild_of(ctx)
        await ctx.defer(ephemeral=True)
        readable, hidden = await self._mine(guild, ctx.author)

        lines = [f"• {_clip(n.text, 150)} — <#{n.source_id}> · {n.created:%Y-%m-%d}" for n in readable[:_PAGE]]
        text = "\n".join(lines) or "ตอนนี้หนูยังไม่ได้จดอะไรเกี่ยวกับเซนเซย์ไว้เลยค่ะ"
        if len(readable) > _PAGE:
            text += f"\n…และอีก {len(readable) - _PAGE} เรื่อง"
        if hidden:
            text += f"\n\nอีก {hidden} เรื่องมาจากช่องที่เซนเซย์อ่านไม่ได้ ใช้ `/memory forget` ให้หนูลืมได้ค่ะ"
        if self.store.is_opted_out(guild.id, ctx.author.id):
            text += "\n\nตอนนี้เซนเซย์ตั้งให้หนู **ไม่จำ** เรื่องของเซนเซย์อยู่ (`/memory optin` เพื่อเปลี่ยน)"
        await ctx.respond(embed=info_embed("📖 สิ่งที่หนูจำเกี่ยวกับเซนเซย์", text), ephemeral=True)

    @memory.command(name="forget", description="🗑️ เลือกเรื่องของตัวเองที่ต้องการให้ AI ลืม (เห็นคนเดียว)")
    async def memory_forget(self, ctx: discord.ApplicationContext) -> None:
        guild = _guild_of(ctx)
        await ctx.defer(ephemeral=True)
        readable, hidden = await self._mine(guild, ctx.author)
        total = len(readable) + hidden
        if not total:
            await ctx.respond(
                embed=info_embed("ไม่มีอะไรให้ลืมค่ะ", "หนูไม่ได้จดเรื่องของเซนเซย์ไว้เลยนะคะ (๑•̀ᴗ•́)و"), ephemeral=True
            )
            return

        shown = readable[:25]  # a select menu holds 25
        text = "เลือกเรื่องที่ให้หนูลืม หรือกดปุ่มสีแดงเพื่อให้ลืมทุกเรื่องเลยก็ได้ค่ะ"
        if len(readable) > len(shown):
            text += f"\n(แสดง {len(shown)} เรื่องล่าสุดจาก {len(readable)} เรื่อง)"
        if hidden:
            text += f"\nอีก {hidden} เรื่องมาจากช่องที่เซนเซย์อ่านไม่ได้ ลบได้ด้วยปุ่มสีแดงเท่านั้นค่ะ"
        await ctx.respond(
            embed=info_embed("🗑️ ให้หนูลืมเรื่องไหนดีคะ", text),
            view=_ForgetMenu(self.store, guild, ctx.author, shown, total),
            ephemeral=True,
        )

    # ── /memory optout, optin ─────────────────────────────────────────────

    @memory.command(name="optout", description="🚫 ให้ AI ลืมเรื่องของตัวเองทั้งหมดและไม่จำอีก")
    async def memory_optout(self, ctx: discord.ApplicationContext) -> None:
        guild = _guild_of(ctx)
        await ctx.defer(ephemeral=True)
        mem = await self.store.ensure_loaded(guild)
        if ctx.author.id in mem.optouts:
            raise UserWarning("ตั้งไว้แล้วค่ะ", "หนูไม่จำเรื่องของเซนเซย์อยู่แล้วนะคะ (`/memory optin` ถ้าเปลี่ยนใจ)")

        member = ctx.author
        total = len(self.store.about_or_by(guild.id, member.id))

        async def run() -> discord.Embed:
            gone = await self.store.forget_member(guild, member.id)
            await self.store.add_optout(guild, member.id)
            return success_embed(
                "ได้เลยค่ะ",
                f"หนูลืมไป {gone} เรื่อง และจะไม่จำเรื่องของเซนเซย์หรือที่เซนเซย์บอกอีกนะคะ "
                "ถ้าเปลี่ยนใจใช้ `/memory optin` ได้เลยค่ะ",
            )

        await ctx.respond(
            embed=warning_embed(
                "ไม่ให้หนูจำเรื่องของเซนเซย์ใช่มั้ยคะ?",
                f"หนูจะลืม {total} เรื่องที่มีอยู่ และต่อไปจะไม่จดเรื่องที่พูดถึงเซนเซย์ "
                "หรือที่เซนเซย์เป็นคนบอกค่ะ",
            ),
            view=_Confirm(run),
            ephemeral=True,
        )

    @memory.command(name="optin", description="✅ ให้ AI กลับมาจำเรื่องของตัวเองได้อีก (หลังเคยสั่งไม่ให้จำ)")
    async def memory_optin(self, ctx: discord.ApplicationContext) -> None:
        guild = _guild_of(ctx)
        await ctx.defer(ephemeral=True)
        if not await self.store.remove_optout(guild, ctx.author.id):
            raise UserWarning("ไม่ได้ตั้งไว้ค่ะ", "เซนเซย์ไม่ได้สั่งให้หนูหยุดจำนี่นา (๑•̀ᴗ•́)و")
        await ctx.respond(
            embed=success_embed("ได้เลยค่ะ", "ต่อไปหนูจะจำเรื่องของเซนเซย์ได้อีกครั้งนะคะ แต่ต้องขอให้จำก่อนเหมือนเดิมน้า"),
            ephemeral=True,
        )


def setup(bot: discord.Bot) -> None:
    bot.add_cog(MemoryCog(bot))
