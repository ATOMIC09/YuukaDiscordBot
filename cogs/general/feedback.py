import discord
from discord import ui
from discord.ext import commands
from bot.logger import logger
from bot.config import config
from utils.embeds import build_embed, success_embed, error_embed
from utils.errors import UserError

class FeedbackModal(ui.Modal):
    def __init__(self, bot: discord.Bot, **kwargs):
        super().__init__(title='มีอะไรอยากบอก?', **kwargs)
        self.bot = bot
        
        self.message_input = ui.InputText(
            label='Answer',
            style=discord.InputTextStyle.paragraph,
            placeholder="พิมพ์ข้อเสนอแนะหรือปัญหาที่นี่...",
            required=True
        )
        self.add_item(self.message_input)

    async def callback(self, interaction: discord.Interaction):
        if not config.feedback_channel_id:
            logger.warning("Feedback channel ID is not configured.")
            raise UserError("เกิดข้อผิดพลาด", "ไม่ได้ตั้งค่าช่องสำหรับรับ Feedback กรุณาแจ้งแอดมินนะคะ! (；￣Д￣)")

        channel = self.bot.get_channel(config.feedback_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(config.feedback_channel_id)
            except discord.NotFound:
                raise UserError("เกิดข้อผิดพลาด", "หาช่องรับ Feedback ไม่เจอค่ะ เซนเซย์ (；￣Д￣)")

        # Build feedback embed
        embed = build_embed(
            title="📨 Feedback",
            color=0x45E2A4,
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.timestamp = interaction.created_at
        
        guild_info = f"`{interaction.guild.name}` ({interaction.guild_id})" if interaction.guild else "Direct Message"
        category_info = f"`{interaction.channel.category.name}` ({interaction.channel.category_id})" if interaction.guild and hasattr(interaction.channel, "category") and interaction.channel.category else "None"
        channel_info = f"`{interaction.channel.name}` ({interaction.channel_id})" if interaction.guild else "Direct Message"
        
        embed.add_field(name="เซิร์ฟเวอร์", value=guild_info, inline=False)
        embed.add_field(name="หมวดหมู่", value=category_info, inline=False)
        embed.add_field(name="ช่อง", value=channel_info, inline=False)
        embed.add_field(name="ผู้เขียน", value=f"`{interaction.user}` ({interaction.user.id})", inline=False)
        embed.add_field(name="เนื้อหา", value=f"```{self.message_input.value}```", inline=False)
        
        await channel.send(embed=embed)
        await interaction.response.send_message(
            embed=success_embed("ส่งข้อความเรียบร้อย", "หนูส่ง Feedback ไปให้แอดมินแล้วนะคะ ขอบคุณที่แนะนำค่ะ! (๑>◡<๑)"),
            ephemeral=True
        )
        logger.info(f"Feedback sent by {interaction.user} ({interaction.user.id})")

    async def on_error(self, error: Exception, interaction: discord.Interaction):
        if isinstance(error, UserError):
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed(error.title, error.description), ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed(error.title, error.description), ephemeral=True)
        else:
            logger.exception(f"Unhandled error in FeedbackModal: {error}")
            embed = error_embed("เกิดข้อผิดพลาดค่ะ", "อ๊ะ! มีอะไรบางอย่างผิดพลาดแหละค่ะ... (´-ω-`)")
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

class FeedbackCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="feedback", description="📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง")
    async def feedback(self, ctx: discord.ApplicationContext):
        modal = FeedbackModal(self.bot)
        await ctx.send_modal(modal)

def setup(bot: discord.Bot):
    bot.add_cog(FeedbackCog(bot))
