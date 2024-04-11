import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize

class Resize(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Resize cog loaded")

    @app_commands.command(name='resize', description="📏 ปรับขนาดภาพด้วยบอท")
    @app_commands.describe(width='ความกว้างที่จะปรับ', height='ความสูงที่จะปรับ')
    async def resize(self, interaction: discord.Interaction, width: int, height: int):
        # Get last imange from channel
        channel = self.client.get_channel(interaction.channel_id)
        message = await discord.utils.get(channel.history(limit=10))

        if len(message.attachments) > 0:
            for attachment in message.attachments:
                await self.log_cog.sendlog(interaction, data={'content': attachment.filename})
        else:
            await interaction.response.send_message(f"❌ **ไม่พบภาพที่ถูกแนบมา**")
            return


        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        if attachment.filename.split('.')[-1] in ['gif', 'svg']:
            await interaction.edit_original_response(content=f"❌ **ไม่รองรับภาพนี้**")
            await self.log_cog.runcomplete('⚠️')
            return
        
        img_processsing.save_image_from_url(attachment.url, f"temp/image/{attachment.filename}")
        source_shape = img_processsing.get_shape(f"temp/image/{attachment.filename}")
        status = img_processsing.resize(f"temp/image/{attachment.filename}", width, height)
        if status:
            await interaction.edit_original_response(content=f"❌ **{status}**")
            await self.log_cog.runcomplete('⚠️')
            return
        
        result_shape = img_processsing.get_shape(f"temp/image/{attachment.filename}")
        path = f'temp/image/{attachment.filename}'
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `{source_shape[0]}x{source_shape[1]} -> {result_shape[0]}x{result_shape[1]} ({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Resize cog")
    await client.add_cog(Resize(client))