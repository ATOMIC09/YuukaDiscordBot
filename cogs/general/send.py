import discord
from discord.ext import commands
from bot.logger import logger
from bot.config import config
from utils.embeds import success_embed
from utils.errors import UserError

class SendCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="send", description="📨 ส่งข้อความด้วยบอท (เฉพาะเจ้าของ)")
    async def send(self, ctx: discord.ApplicationContext, channel: discord.Option(str, "ช่องข้อความที่จะส่ง (ID หรือ #channel)"), message: discord.Option(str, "ข้อความ")): # type: ignore
        # Restrict to user ID
        if not config.owner_id or ctx.author.id != config.owner_id:
            raise UserError("ไม่มีสิทธิ์", "หนูรับคำสั่งนี้จากเซนเซย์ที่เป็นเจ้าของเท่านั้นนะคะ! ಠ_ಠ")

        await ctx.defer(ephemeral=True)

        channel_id_str = channel.strip()
        if channel_id_str.startswith('#'):
            channel_id_str = channel_id_str[1:]
        elif channel_id_str.startswith('<#') and channel_id_str.endswith('>'):
            channel_id_str = channel_id_str[2:-1]
            
        try:
            channel_id = int(channel_id_str)
            channel_obj = await self.bot.fetch_channel(channel_id)
            
            if not isinstance(channel_obj, discord.TextChannel):
                raise UserError("ประเภทช่องไม่ถูกต้อง", "ช่องนี้ไม่ใช่ช่องข้อความปกตินะคะ เซนเซย์")
                
        except discord.NotFound:
            raise UserError("ไม่พบช่องข้อความ", f"ไม่พบช่องข้อความที่มี ID: `{channel_id}`")
        except discord.Forbidden:
            raise UserError("ไม่มีสิทธิ์เข้าถึง", f"หนูไม่มีสิทธิ์เข้าถึงช่องที่มี ID: `{channel_id}` ค่ะ")
        except ValueError:
            raise UserError("รูปแบบไม่ถูกต้อง", f"รูปแบบ Channel ID ไม่ถูกต้อง: `{channel}`\nใส่เป็นไอดีหรือแท็ก #ชื่อช่อง นะคะ")

        try:
            await channel_obj.send(message)
            await ctx.followup.send(embed=success_embed("ส่งเรียบร้อย", f"หนูส่งข้อความไปที่ {channel_obj.mention} ให้แล้วนะคะ! (๑>◡<๑)"))
            logger.info(f"Send command used by {ctx.author}: '{message}' to {channel_obj.name}")
        except Exception as e:
            logger.error(f"Failed to send message to {channel_obj.name}: {e}")
            raise UserError("เกิดข้อผิดพลาด", f"หนูส่งข้อความไม่ได้ค่ะ: `{e}`")

def setup(bot: discord.Bot):
    bot.add_cog(SendCog(bot))
