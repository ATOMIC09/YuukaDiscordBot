import discord
from discord.ext import commands
from discord import app_commands

class Send(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Send cog loaded")

    @app_commands.command(name='send', description="📨 ส่งข้อความด้วยบอท")
    @app_commands.describe(channel="ช่องข้อความที่จะส่ง",message="ข้อความ")
    async def send(self, interaction: discord.Interaction, channel: discord.TextChannel, *, message: str):
        await self.log_cog.sendlog(interaction, data={'content': f'{channel.name} ({channel.id}) กับข้อความ "{message}"'})
        await interaction.response.send_message(f'"{message}" ถูกส่งไปยัง {channel.mention}',ephemeral=True)
        await channel.send(message)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Send cog")
    await client.add_cog(Send(client))