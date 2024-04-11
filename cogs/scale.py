import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize

class Scale(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Scale cog loaded")

    @app_commands.command(name='scale', description="📏 ปรับขนาดภาพด้วยบอท")
    @app_commands.describe(scale='ขนาดที่จะปรับ เช่น 2 หรือ 200% คือการขยายภาพขึ้นเป็นสองเท่า')
    async def scale(self, interaction: discord.Interaction, scale: str): 
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
        status = img_processsing.scale(f"temp/image/{attachment.filename}", float(scale.split('%')[0])/100 if '%' in scale else float(scale))
        if status:
            await interaction.edit_original_response(content=f"❌ **{status}**")
            await self.log_cog.runcomplete('⚠️')
            return
        
        result_shape = img_processsing.get_shape(f"temp/image/{attachment.filename}")

        get_file_name_only = img_processsing.get_filename(attachment.url)[1]

        path = f'temp/image/{attachment.filename}'
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `{source_shape[0]}x{source_shape[1]} -> {result_shape[0]}x{result_shape[1]} ({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Scale cog")
    await client.add_cog(Scale(client))