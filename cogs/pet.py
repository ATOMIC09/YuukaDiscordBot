import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize
from petpetgif import petpet

class Pet(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Pet cog loaded")

    @app_commands.command(name='pet', description="🐶 ตบหลังแล้วลูบหัว")
    async def pet(self, interaction: discord.Interaction):
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
        img_processsing.save_image_from_url(attachment.url, f"temp/image/{attachment.filename}")
        file_name_only = img_processsing.get_filename(attachment.filename)[1]

        petpet.make(f'temp/image/{attachment.filename}', f'temp/image/{file_name_only}_petpet.gif')
        path = f'temp/image/{file_name_only}_petpet.gif'
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
    print("Setting up Pet cog")
    await client.add_cog(Pet(client))