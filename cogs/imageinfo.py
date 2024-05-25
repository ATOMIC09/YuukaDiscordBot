import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processsing as img_processsing
import utils.filesize as filesize

class ImageInfo(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.context_menu = app_commands.ContextMenu(
            name='ImageInfo',
            callback=self.imageinfo,
        )
        self.client.tree.add_command(self.context_menu)

    @commands.Cog.listener()
    async def on_ready(self):
        print("ImageInfo cog loaded")

    async def imageinfo(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await self.log_cog.sendlog(interaction, data={'content': message.attachments[0].filename})
        except IndexError:
            await interaction.response.send_message(f"❌ **[ไม่พบภาพที่ถูกแนบมา](<{message.jump_url}>)**", ephemeral=True)
            return

        img_processsing.save_image_from_url(message.attachments[0].url, f"temp/image/{message.attachments[0].filename}")

        info = img_processsing.imginfo(f"temp/image/{message.attachments[0].filename}")
        channel = info["channel_type"]
        width = info["width"]
        height = info["height"]
        size = filesize.getsize(f"temp/image/{message.attachments[0].filename}")
        last_modified = info["last_modified"]
        date_taken = info["date_taken"]
        camera_make = info["camera_make"]
        camera_model = info["camera_model"]
        exposure_time = info["exposure_time"]
        f_number = info["f_number"]
        iso_speed = info["iso_speed"]
        focal_length = info["focal_length"]

        embed = discord.Embed(title="**🔦 คุณสมบัติรูปภาพ**", color=0xff3859)
        embed.timestamp = interaction.created_at
        embed.add_field(name="🖨️ ชื่อไฟล์", value=f"`{message.attachments[0].filename}`", inline=False)
        embed.add_field(name="📂 ขนาดไฟล์", value=f"`{size}`", inline=False)
        embed.add_field(name="🌈 ช่อง", value=f"`{channel}`", inline=False)
        embed.add_field(name="📏 ความกว้าง", value=f"`{width} pixels`", inline=False)
        embed.add_field(name="📐 ความสูง", value=f"`{height} pixels`", inline=False)
        embed.add_field(name="🪄 ความละเอียด", value=f"`{width}x{height}`", inline=False)
        embed.add_field(name="📅 แก้ไขล่าสุด", value=f"`{last_modified}`", inline=False)
        embed.add_field(name="📸 ถ่ายเมื่อ", value=f"`{date_taken}`", inline=False)
        embed.add_field(name="📷 กล้อง", value=f"`{camera_make} {camera_model}`", inline=False)
        embed.add_field(name="⏱️ ความเร็วชัตเตอร์", value=f"`{exposure_time}`", inline=False)
        embed.add_field(name="🔍 รูรับแสง", value=f"`f/{f_number}`", inline=False)
        embed.add_field(name="📈 ค่า ISO", value=f"`{iso_speed}`", inline=False)
        embed.add_field(name="🔭 ความยาวโฟกัส", value=f"`{focal_length}`", inline=False)
        
        await interaction.response.send_message(embed=embed)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up ImageInfo cog")
    await client.add_cog(ImageInfo(client))
