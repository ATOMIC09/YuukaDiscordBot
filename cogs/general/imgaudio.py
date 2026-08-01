import discord
from discord.ext import commands
import os
import tempfile
import aiohttp
from bot.logger import logger
from utils.video import merge_image_audio
from utils.embeds import error_embed, success_embed, info_embed
from utils.errors import UserError

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff')
AUDIO_EXTS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.wma', '.aac', '.opus', '.3gp', '.mp4')

class ImgAudioCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name='imgaudio', description="🎵 สร้างคลิปจากภาพและเสียงล่าสุดในช่อง")
    async def imgaudio(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=False)
        
        channel = ctx.channel
        
        image_attachment = None
        image_message = None
        audio_attachment = None
        audio_message = None
        
        # Scan last 20 messages for an image and an audio file
        async for message in channel.history(limit=20):
            for attachment in message.attachments:
                lower_name = attachment.filename.lower()
                
                # Found image
                if image_attachment is None and lower_name.endswith(IMAGE_EXTS):
                    image_attachment = attachment
                    image_message = message
                    
                # Found audio
                if audio_attachment is None and lower_name.endswith(AUDIO_EXTS):
                    audio_attachment = attachment
                    audio_message = message
                    
            if image_attachment and audio_attachment:
                break
                
        if not image_attachment or not audio_attachment:
            raise UserError(
                "หาไฟล์ไม่ครบค่ะ",
                "หนูหาภาพและเสียงใน 20 ข้อความล่าสุดไม่เจอเลยค่ะ เซนเซย์ส่งมาให้ครบก่อนน้า (´-ω-`)"
            )
            
        await ctx.edit(
            content=None, 
            embed=info_embed("กำลังสร้างคลิปนะคะ...", "<a:AppleLoadingGIF:1052465926487953428> รอแป๊บนึงน้า เซนเซย์... (๑>◡<๑)")
        )
        
        # Create a secure temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            img_path = os.path.join(tmpdir, image_attachment.filename)
            aud_path = os.path.join(tmpdir, audio_attachment.filename)
            out_filename = f"{os.path.splitext(image_attachment.filename)[0]}_{os.path.splitext(audio_attachment.filename)[0]}.mp4"
            out_path = os.path.join(tmpdir, out_filename)
            
            try:
                # Add reactions
                try:
                    await image_message.add_reaction("🖼️")
                    await audio_message.add_reaction("🔉")
                except discord.HTTPException:
                    pass
                    
                # Download files using Pycord's internal session which uses the ThreadedResolver
                await image_attachment.save(img_path)
                await audio_attachment.save(aud_path)

                # Discord's per-file limit depends on the destination guild's boost tier
                # (as low as 10MB on non-boosted servers), not a flat 25MB.
                upload_limit = ctx.guild.filesize_limit if ctx.guild else 10 * 1024 * 1024
                safe_upload_limit = int(upload_limit * 0.97)

                # Merge
                used_encoder = await merge_image_audio(img_path, aud_path, out_path, safe_upload_limit)

                if not hasattr(ctx.bot, "command_extras"):
                    ctx.bot.command_extras = {}
                ctx.bot.command_extras[ctx.interaction.id] = {"Encoder": used_encoder}

                file_size = os.path.getsize(out_path)
                size_mb = file_size / (1024 * 1024)

                if file_size > upload_limit:
                    limit_mb = upload_limit / (1024 * 1024)
                    raise UserError(
                        "ไฟล์ใหญ่เกินไปค่ะ",
                        f"ไฟล์วิดีโอที่ได้มีขนาด {size_mb:.2f} MB ซึ่งใหญ่เกินกว่า {limit_mb:.0f}MB ที่ห้องนี้รับได้นะคะ (；￣Д￣)"
                    )
                
                # Send
                file = discord.File(out_path, filename=out_filename)
                await ctx.edit(content=None, embed=success_embed("สร้างคลิปเสร็จแล้ว!", f"ไฟล์ขนาด `{size_mb:.2f} MB` ค่ะ (๑>◡<๑)"), file=file)
                file.close() # Explicitly close the file handle so Windows can delete the temp directory!
                logger.info(f"ImgAudio successful for {ctx.author}: {out_filename}")
                
            except Exception as e:
                logger.error(f"ImgAudio error: {e}")
                raise UserError("เกิดข้อผิดพลาด", f"หนูรวมไฟล์ให้ไม่ได้ค่ะ: `{str(e)}` (´-ω-`)")

def setup(bot: discord.Bot):
    bot.add_cog(ImgAudioCog(bot))
