import discord
from discord.ext import commands
from discord import app_commands

class Ping(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Ping cog loaded")

    @app_commands.command(name="ping", description="⌛ วัดความเร็วในการตอบสนองของบอท")
    async def ping(self, interaction: discord.Interaction):
        bot_latency = round(self.client.latency * 1000)
        await interaction.response.send_message(f"Pong! {bot_latency} ms.")
        await self.log_cog.sendlog(interaction)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client):
    print("Setting up Ping cog")
    await client.add_cog(Ping(client))