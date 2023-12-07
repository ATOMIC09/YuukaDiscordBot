import discord
from discord.ext import commands
from discord import app_commands
import shutil
import utils.img_processsing as img_processsing
import utils.filesize as filesize

class Deepfry(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.context_menu = app_commands.ContextMenu(
            name='Deepfry',
            callback=self.deepfry,
        )
        self.client.tree.add_command(self.context_menu)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Deepfry cog loaded")

    async def deepfry(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await self.log_cog.sendlog(interaction, data={'content': message.attachments[0].filename})
        except IndexError:
            await interaction.response.send_message(f"❌ **[ไม่พบภาพที่ถูกแนบมา](<{message.jump_url}>)**", ephemeral=True)
            return

        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        img_processsing.save_image_from_url(message.attachments[0].url, f"temp/deepfry/deepfryer_input/{message.attachments[0].filename}")
        img_processsing.deepfry(f"temp/deepfry/deepfryer_input/{message.attachments[0].filename}")

        get_file_name_only = img_processsing.get_filename(message.attachments[0].url)[1]

        path = f'temp/deepfry/deepfryer_output/{get_file_name_only}_deepfried.png'
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Deepfry cog")
    await client.add_cog(Deepfry(client))