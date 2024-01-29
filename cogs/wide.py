import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize

class Wide(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.context_menu = app_commands.ContextMenu(
            name='Wide',
            callback=self.wide,
        )
        self.client.tree.add_command(self.context_menu)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Wide cog loaded")

    async def wide(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await self.log_cog.sendlog(interaction, data={'content': message.attachments[0].filename})
        except IndexError:
            await interaction.response.send_message(f"❌ **[ไม่พบภาพที่ถูกแนบมา](<{message.jump_url}>)**", ephemeral=True)
            return

        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        img_processsing.save_image_from_url(message.attachments[0].url, f"temp/image/{message.attachments[0].filename}")
        source_shape = img_processsing.get_shape(f"temp/image/{message.attachments[0].filename}")
        img_processsing.wide(f"temp/image/{message.attachments[0].filename}",2)
        result_shape = img_processsing.get_shape(f"temp/image/{message.attachments[0].filename}")

        path = f'temp/image/{message.attachments[0].filename}'
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `{source_shape[0]}x{source_shape[1]} -> {result_shape[0]}x{result_shape[1]} ({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        
async def setup(client: commands.Bot):
    print("Setting up Wide cog")
    await client.add_cog(Wide(client))