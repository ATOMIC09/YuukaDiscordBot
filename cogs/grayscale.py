import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize
import os

class Grayscale(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.context_menu = app_commands.ContextMenu(
            name='Grayscale',
            callback=self.grayscale,
        )
        self.client.tree.add_command(self.context_menu)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Grayscale cog loaded")

    async def grayscale(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await self.log_cog.sendlog(interaction, data={'content': message.attachments[0].filename})
        except IndexError:
            await interaction.response.send_message(f"❌ **[ไม่พบภาพที่ถูกแนบมา](<{message.jump_url}>)**", ephemeral=True)
            return

        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        img_processsing.save_image_from_url(message.attachments[0].url, f"temp/image/{message.attachments[0].filename}")

        get_file_name_only = img_processsing.get_filename(message.attachments[0].url)[1]
        ext = img_processsing.get_filename(message.attachments[0].url)[2]
        
        img_processsing.grayscale(f"temp/image/{message.attachments[0].filename}")
        os.rename(f"temp/image/{message.attachments[0].filename}", f"temp/image/{get_file_name_only}_grayscale.{ext}")
        path = f'temp/image/{get_file_name_only}_grayscale.{ext}'
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        
        try:
            await interaction.followup.send(file=file_name)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        except:
            await interaction.edit_original_response(content=f"❌ **ไฟล์ใหญ่เกินไป `({filesize.getsize(path)})`**")
            await self.log_cog.runcomplete('⚠️')
            return
        
async def setup(client: commands.Bot):
    print("Setting up Grayscale cog")
    await client.add_cog(Grayscale(client))