import discord
from discord import ui
from discord.ext import commands
from discord import app_commands

class Feedback(commands.Cog):
    def __init__(self, client: commands.Bot ):
        self.client = client
        self.log_cog = client.get_cog("Log")

    class FeedbackModal(ui.Modal, title='มีอะไรอยากบอก?'):
        def __init__(self):
            self.message = ui.TextInput(label='Answer', style=discord.TextStyle.paragraph)

        async def on_submit(self, interaction: discord.Interaction):
            channel = self.client.get_channel(1002616395495907328)
            await interaction.response.send_message(f'ส่งข้อความเรียบร้อย ✅', ephemeral=True)
            feedback = discord.Embed(title="**📨 Feedback**", color=0x45E2A4)
            feedback.set_author(name=interaction.user, icon_url=interaction.user.display_avatar.url)
            feedback.timestamp = interaction.created_at
            feedback.add_field(name="เซิร์ฟเวอร์", value=f"`{interaction.guild}` ({interaction.guild_id})")
            feedback.add_field(name="หมวดหมู่", value=f"`{interaction.channel.category.name}` ({interaction.channel.category.id})")
            feedback.add_field(name="ช่อง", value=f"`{interaction.channel}` ({interaction.channel_id})")
            feedback.add_field(name="ผู้เขียน", value=f"`{interaction.user}` ({interaction.user.id})")
            feedback.add_field(name="เนื้อหา", value=f"```{self.message}```")
            await channel.send(embed=feedback)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Feedback cog loaded")

    @app_commands.command(name="feedback", description="📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง")
    async def feedback_command(self, interaction: discord.Interaction):
        await self.log_cog.sendlog(interaction)
        await interaction.response.send_modal(self.FeedbackModal())

async def setup(client: commands.Bot):
    print("Setting up Feedback cog")
    await client.add_cog(Feedback(client))