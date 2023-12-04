import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

class Announce(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Announce cog loaded")

    @app_commands.command(name='announce', description="📢 ประกาศ (เฉพาะผู้ดูแล)")
    @app_commands.describe(message="ข้อความประกาศ")
    async def announce(self, interaction: discord.Interaction, *, message: Optional[str]):
        if interaction.user.id == 269000561255383040:
            if self.client.isAnnounce == False:
                await self.log_cog.sendlog(interaction, data={'content': message})
                self.client.isAnnounce = True
                await self.client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
                await interaction.response.send_message(f'✅ **ประกาศ** {message} **เรียบร้อย**',ephemeral=True)
                await self.log_cog.runcomplete('<:Approve:921703512382009354>')
            else:
                await self.log_cog.sendlog(interaction)
                self.client.isAnnounce = False
                await interaction.response.send_message(f'⏹ **หยุดประกาศเรียบร้อย**',ephemeral=True)
                await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Announce cog")
    await client.add_cog(Announce(client))