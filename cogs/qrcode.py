import discord
from discord.ext import commands
from discord import app_commands
import utils.img_processing as img_processing
import utils.filesize as filesize
import qrcode
from typing import Optional
from PIL import Image
import uuid

class QRCode(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("QRCode cog loaded")

    @app_commands.command(name='qr', description="📸 สร้าง QR Code")
    @app_commands.describe(text='ข้อความที่จะสร้าง QR Code', logo='ลิ้งภาพของโลโก้ที่จะใส่ลงใน QR Code', box_size='จำนวนพิกเซลแต่ละช่อง', border='ความหนาของขอบ', version='จำนวน 1-40 ที่ควบคุมขนาดของ QR Code (version 1 = 21x21 matrix)')
    async def qr(self, interaction: discord.Interaction, text: str, logo: Optional[str], box_size: Optional[int] = 10, border: Optional[int] = 4, version: Optional[int] = 1):
        await self.log_cog.sendlog(interaction, data={'content': f'box_size: {box_size} border: {border} version: {version}'})
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        
        if logo != None:
            file_name = img_processing.get_filename(logo)[0]
            img_processing.save_image_from_url(logo, f"temp/image/{file_name}")
            logolocal = Image.open(f"temp/image/{file_name}")

        qr = qrcode.QRCode(
            version = version,
            error_correction = qrcode.constants.ERROR_CORRECT_L, # about 7% or less errors can be corrected.
            box_size = box_size,
            border = border,
        )
        qr.add_data(text)
        qr.make(fit=True)
        
        if logo == None:
            img = qr.make_image(fill_color="black", back_color="white")
        else:
            img = qr.make_image().convert('RGB')
            pos = ((img.size[0] - logolocal.size[0]) // 2, (img.size[1] - logolocal.size[1]) // 2)
            img.paste(logolocal, pos)

        path = f"temp/image/{uuid.uuid4().hex}.png"
        img.save(path)

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
    print("Setting up QRCode cog")
    await client.add_cog(QRCode(client))