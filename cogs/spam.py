import discord
from discord.ext import commands
from discord import app_commands
import asyncio

class Spam(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.stopSpam = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print("Spam cog loaded")

    @app_commands.command(name='spam', description="📢 สแปมคนไม่มา")
    @app_commands.describe(member="ผู้ใช้", message="ข้อความ", delay="การหน่วงเวลา", amount="จำนวนครั้ง")
    async def spam(self, interaction: discord.Interaction, member: discord.Member, *, message: str, delay: int = 2, amount: int = 5):
        await self.log_cog.sendlog(interaction, data={'content': f'{member.name} ({member.id}) กับข้อความ "{message}" ที่จะส่ง {amount} ครั้ง และห่างกัน {delay} วินาที'})
        guild = interaction.guild_id
        self.stopSpam[guild] = False

        stop = discord.ui.Button(label="Stop",style=discord.ButtonStyle.red)
        async def stop_callback(interaction):
            self.stopSpam[guild] = True

        stop.callback = stop_callback
        view = discord.ui.View()
        view.add_item(stop)
        await interaction.response.send_message(content=f'<a:LoadingGIF:1052561472263299133> **กำลังสแปม** {message} **กับ** <@{member.id}>',ephemeral=True,view=view)
        
        for i in range(amount):
            if self.stopSpam[guild] == False:
                await asyncio.sleep(delay)
                await interaction.followup.send(f'{message} <@{member.id}>')
            else:
                break
        if self.stopSpam[guild] == False:
            await interaction.edit_original_response(content=f'✅ **สแปม** {message} **กับ** <@{member.id}> **จบแล้ว**',view=None)    
        else:
            await interaction.edit_original_response(content=f'⛔ **หยุดสแปม** {message} **กับ** <@{member.id}> **แล้ว**',view=None)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    await client.add_cog(Spam(client))
    print("Setting up Spam cog")