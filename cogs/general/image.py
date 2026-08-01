import discord
from discord.ext import commands
import io
import os
import asyncio
from bot.logger import logger
from utils.embeds import success_embed, error_embed, info_embed
import utils.image as img_utils
from utils.errors import UserError, UserWarning

class ImageCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    async def _get_image_bytes(self, ctx: discord.ApplicationContext, attachment: discord.Attachment | None) -> bytes:
        if attachment:
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                raise UserError("ไฟล์ไม่ถูกต้อง", "เซนเซย์ต้องแนบไฟล์รูปภาพเท่านั้นนะคะ! (,,#ﾟДﾟ)")
            return await attachment.read()
        else:
            img_bytes = await img_utils.fetch_recent_image(ctx.channel)
            if img_bytes:
                return img_bytes
            raise UserError("ไม่พบรูปภาพ", "หนูหารูปภาพในแชทล่าสุดไม่เจอเลยค่ะ เซนเซย์ลองแนบรูปมาใหม่นะคะ (・_・ヾ")

    # Helper method to get image bytes from message commands
    async def _get_message_image_bytes(self, message: discord.Message) -> tuple[bytes, str]:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                return await attachment.read(), attachment.filename
        raise UserError("ไม่พบรูปภาพ", "ข้อความที่เซนเซย์เลือกไม่มีรูปภาพเลยนี่คะ! หลอกหนูเหรอ (,,#ﾟДﾟ)")

    # Helper method to get media (image or video) bytes from message commands
    async def _get_message_media_bytes(self, message: discord.Message) -> tuple[bytes, str, bool]:
        for attachment in message.attachments:
            if attachment.content_type:
                if attachment.content_type.startswith("image/"):
                    return await attachment.read(), attachment.filename, False
                elif attachment.content_type.startswith("video/"):
                    return await attachment.read(), attachment.filename, True
        raise UserError("ไม่พบรูปภาพหรือวิดีโอ", "ข้อความที่เซนเซย์เลือกไม่มีรูปภาพหรือวิดีโอเลยนี่คะ! หลอกหนูเหรอ (,,#ﾟДﾟ)")

    def _format_size(self, size_bytes: int) -> str:
        size_mb = size_bytes / (1024 * 1024)
        return f"{size_mb:.2f} MB" if size_mb >= 1 else f"{size_bytes/1024:.2f} KB"

    def _format_footer(self, size_bytes: int, old_size: tuple[int, int], new_size: tuple[int, int]) -> str:
        size_str = self._format_size(size_bytes)
        if old_size == new_size:
            return f"ขนาดไฟล์: {size_str} | ความละเอียด: {new_size[0]}x{new_size[1]}"
        else:
            return f"ขนาดไฟล์: {size_str} | ความละเอียด: {old_size[0]}x{old_size[1]} ➔ {new_size[0]}x{new_size[1]}"

    # --- Slash Commands ---
    image = discord.SlashCommandGroup("image", "จัดการและตกแต่งรูปภาพ")

    @image.command(name="pet", description="🐶 สร้างภาพลูบหัว (Petpet)")
    async def pet(self, ctx: discord.ApplicationContext, image: discord.Option(discord.Attachment, "รูปภาพที่ต้องการ (ถ้าไม่ใส่จะดึงจากแชทล่าสุด)", required=False)): # type: ignore
        await ctx.defer()
        img_bytes = await self._get_image_bytes(ctx, image)
        
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_petpet, img_bytes)
            file = discord.File(output_io, filename=f"petpet.{ext}")
            
            embed = success_embed("Petpet!", "ลูบหัวเรียบร้อยแล้วค่ะเซนเซย์ (๑>◡<๑)")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in pet: {e}")
            raise UserError("เกิดข้อผิดพลาด", "หนูทำรูปนี้ไม่ได้ค่ะ ไฟล์อาจจะเสียหรือใหญ่เกินไป (╥﹏╥)")

    @image.command(name="resize", description="📏 ปรับขนาดรูปภาพตามพิกเซล")
    async def resize(self, ctx: discord.ApplicationContext, width: discord.Option(int, "ความกว้าง (Width)"), height: discord.Option(int, "ความสูง (Height)"), image: discord.Option(discord.Attachment, "รูปภาพที่ต้องการ", required=False)): # type: ignore
        await ctx.defer()
        img_bytes = await self._get_image_bytes(ctx, image)
        
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_resize, img_bytes, width, height)
            file = discord.File(output_io, filename=f"resized.{ext}")
            
            embed = success_embed("Resize", f"ปรับขนาดเป็น `{width}x{height}` เรียบร้อยแล้วค่ะ!")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in resize: {e}")
            raise UserError("เกิดข้อผิดพลาด", "ปรับขนาดไม่สำเร็จค่ะ เซนเซย์ลองอีกรอบนะคะ (；￣Д￣)")

    @image.command(name="scale", description="📐 ย่อ/ขยายรูปภาพตามสัดส่วน")
    async def scale(self, ctx: discord.ApplicationContext, multiplier: discord.Option(float, "ตัวคูณสัดส่วน (เช่น 0.5 ครึ่งนึง, 2.0 สองเท่า)"), image: discord.Option(discord.Attachment, "รูปภาพที่ต้องการ", required=False)): # type: ignore
        await ctx.defer()
        img_bytes = await self._get_image_bytes(ctx, image)
        
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_scale, img_bytes, multiplier)
            file = discord.File(output_io, filename=f"scaled.{ext}")
            
            embed = success_embed("Scale", f"ปรับสัดส่วน `x{multiplier}` เรียบร้อยแล้วค่ะ!")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in scale: {e}")
            raise UserError("เกิดข้อผิดพลาด", "ย่อขยายรูปไม่สำเร็จค่ะ เซนเซย์ ( ˘︹˘ )")

    @image.command(name="qr", description="📸 สร้าง QR Code จากข้อความ")
    async def qr(self, ctx: discord.ApplicationContext, text: discord.Option(str, "ข้อความหรือลิ้งก์สำหรับสร้าง QR Code"), logo: discord.Option(discord.Attachment, "รูปภาพโลโก้ตรงกลาง (ถ้ามี)", required=False)): # type: ignore
        await ctx.defer()
        
        logo_bytes = None
        if logo:
            if not logo.content_type or not logo.content_type.startswith("image/"):
                raise UserError("โลโก้ไม่ถูกต้อง", "ไฟล์โลโก้ต้องเป็นรูปภาพเท่านั้นนะคะ! (＃￣0￣)")
            logo_bytes = await logo.read()
            
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_qr, text, logo_bytes)
            file = discord.File(output_io, filename=f"qrcode.{ext}")
            
            embed = success_embed("QR Code", "สร้างคิวอาร์โค้ดเสร็จแล้วค่ะเซนเซย์! ( • ̀ω•́ )")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in qr: {e}")
            raise UserError("เกิดข้อผิดพลาด", "สร้าง QR Code ไม่สำเร็จค่ะ (；¬д¬)")


    # --- Context Menus (Message Commands) ---
    @discord.message_command(name="Deepfry")
    async def ctx_deepfry(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer()
        media_bytes, filename, is_video = await self._get_message_media_bytes(message)

        upload_limit = ctx.guild.filesize_limit if ctx.guild else 10 * 1024 * 1024
        safe_upload_limit = int(upload_limit * 0.97)

        try:
            if is_video:
                import utils.video as video_utils
                output_io, ext, old_size, new_size, used_encoder = await video_utils.make_deepfry_video(media_bytes, safe_upload_limit)
            else:
                output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_deepfry, media_bytes)
                used_encoder = "PIL (CPU)"

            if not hasattr(ctx.bot, "command_extras"):
                ctx.bot.command_extras = {}
            ctx.bot.command_extras[ctx.interaction.id] = {"Encoder": used_encoder}

            # Safety net: make_deepfry_video already bitrate-targets to fit under the limit,
            # but guard here too in case ffmpeg still overshoots on pathological input
            # (or for the PIL image path, which doesn't target a size at all).
            if output_io.getbuffer().nbytes > upload_limit:
                limit_mb = upload_limit / (1024 * 1024)
                raise UserError("ไฟล์ใหญ่เกินไป", f"ขอโทษค่ะเซนเซย์ แต่พอทอดเสร็จแล้วไฟล์ใหญ่เกิน {limit_mb:.0f}MB หนูส่งให้ไม่ได้ค่ะ (╥﹏╥)")
            
            base_name, _ = os.path.splitext(filename)
            file = discord.File(output_io, filename=f"{base_name}_deepfried.{ext}")
            
            embed = success_embed("Deepfry", "ทอดกรอบเสร็จแล้วค่ะ! ร้อน ๆ เลย (๑•̀ㅂ•́)و✧")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except UserError:
            raise
        except Exception as e:
            logger.error(f"Error in deepfry: {e}")
            raise UserError("เกิดข้อผิดพลาด", "ทอดไม่สำเร็จค่ะ ไฟล์อาจจะไหม้ไปแล้ว (＠_＠)")

    @discord.message_command(name="Grayscale")
    async def ctx_grayscale(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer()
        img_bytes, filename = await self._get_message_image_bytes(message)
        
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_grayscale, img_bytes)
            base_name, _ = os.path.splitext(filename)
            file = discord.File(output_io, filename=f"{base_name}_gray.{ext}")
            
            embed = success_embed("Grayscale", "เปลี่ยนเป็นสีขาวดำเรียบร้อยค่ะ เซนเซย์! ( ⁎ᵕᴗᵕ⁎ )")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in grayscale: {e}")
            raise UserError("เกิดข้อผิดพลาด", "เปลี่ยนสีไม่สำเร็จค่ะ (。-`ω´-)")

    @discord.message_command(name="Wide")
    async def ctx_wide(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer()
        img_bytes, filename = await self._get_message_image_bytes(message)
        
        try:
            output_io, ext, old_size, new_size = await asyncio.to_thread(img_utils.make_wide, img_bytes)
            base_name, _ = os.path.splitext(filename)
            file = discord.File(output_io, filename=f"{base_name}_wide.{ext}")
            
            embed = success_embed("Wide", "ยืดภาพให้กว้าง ๆ แล้วนะคะ! (・`ω´・)")
            embed.set_footer(text=self._format_footer(output_io.getbuffer().nbytes, old_size, new_size))
            await ctx.respond(embed=embed, file=file)
        except Exception as e:
            logger.error(f"Error in wide: {e}")
            raise UserError("เกิดข้อผิดพลาด", "ยืดภาพไม่สำเร็จค่ะ (￣︿￣)")

    @discord.message_command(name="Image Info")
    async def ctx_imageinfo(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer()
        img_bytes, filename = await self._get_message_image_bytes(message)
        
        try:
            info = await asyncio.to_thread(img_utils.get_image_info, img_bytes)
            
            # Format size nicely
            size_str = self._format_size(len(img_bytes))
            
            embed = info_embed("คุณสมบัติรูปภาพ 🔦", f"ข้อมูลของไฟล์ `{filename}` ค่ะเซนเซย์")
            embed.add_field(name="📂 ขนาดไฟล์", value=f"`{size_str}`", inline=True)
            embed.add_field(name="🌈 ช่องสี", value=f"`{info['channel_type']}`", inline=True)
            embed.add_field(name="🪄 ความละเอียด", value=f"`{info['width']}x{info['height']}`", inline=True)
            
            if info['date_taken'] != "N/A":
                embed.add_field(name="📸 ถ่ายเมื่อ", value=f"`{info['date_taken']}`", inline=False)
            if info['camera_make'] != "N/A" or info['camera_model'] != "N/A":
                embed.add_field(name="📷 กล้อง", value=f"`{info['camera_make']} {info['camera_model']}`".strip(), inline=False)
            
            extras = []
            if info['exposure_time'] != "N/A": extras.append(f"**ชัตเตอร์:** `{info['exposure_time']}`")
            if info['f_number'] != "N/A": extras.append(f"**รูรับแสง:** `f/{info['f_number']}`")
            if info['iso_speed'] != "N/A": extras.append(f"**ISO:** `{info['iso_speed']}`")
            if info['focal_length'] != "N/A": extras.append(f"**โฟกัส:** `{info['focal_length']}mm`")
            
            if extras:
                embed.add_field(name="⚙️ ข้อมูล EXIF เพิ่มเติม", value="\n".join(extras), inline=False)
                
            await ctx.respond(embed=embed)
        except Exception as e:
            logger.error(f"Error in image info: {e}")
            raise UserError("เกิดข้อผิดพลาด", "อ่านข้อมูลรูปภาพไม่สำเร็จค่ะ (×_×)")

def setup(bot: discord.Bot):
    bot.add_cog(ImageCog(bot))
