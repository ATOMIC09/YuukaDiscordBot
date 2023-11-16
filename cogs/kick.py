import discord
from discord.ext import commands
from discord import app_commands

class Kick(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Kick cog loaded")

    @app_commands.command(name='kick', description="🦵 เตะสมาชิกจากช่องเสียง")
    @app_commands.describe(member="ผู้ใช้")
    async def kick(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await self.log_cog.sendlog(interaction, data={'content': f'{member.name} ({member.id}) ถูกเตะออกจาก {member.voice.channel}'})
        except AttributeError:
            await self.log_cog.sendlog(interaction, data={'content': f'{member.name} ({member.id})'})
        try:
            await interaction.response.send_message(f'<@{member.id}> ถูกเตะออกจาก `{member.voice.channel}`',ephemeral=True)
            await member.move_to(None)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        except AttributeError:
            await interaction.response.send_message(content="**ถีบใคร? ไม่มีใครให้ถีบอะดิ (●'◡'●)**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client: commands.Bot):
    print("Setting up Kick cog")
    await client.add_cog(Kick(client))