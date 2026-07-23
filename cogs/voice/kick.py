import discord
from discord.ext import commands
from bot.logger import logger
from utils.embeds import success_embed
from utils.errors import UserError, UserWarning

class VoiceKickCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="kick", description="🦵 เตะสมาชิกออกจากห้องเสียง")
    @discord.default_permissions(move_members=True)
    async def kick(self, ctx: discord.ApplicationContext, member: discord.Option(discord.Member, "ผู้ใช้ที่ต้องการเตะ")): # type: ignore
        await ctx.defer()
        
        if not member.voice or not member.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", f"ดูเหมือนว่า {member.display_name} จะไม่ได้อยู่ในห้องเสียงนะคะ (●'◡'●)")
            
        if member.id == self.bot.user.id:
            raise UserError("จะเตะหนูหรอคะ", "ใจร้ายที่สุดเลย! หนูไม่ยอมหรอกนะ (╯°□°)╯︵ ┻━┻")
            
        channel = member.voice.channel
        
        try:
            await member.move_to(None)
            await ctx.respond(embed=success_embed("เตะออกจากห้องเสียง", f"เตะ {member.mention} ออกจากช่อง `{channel.name}` เรียบร้อยแล้วค่ะ! ไปไกล ๆ เลยน้า~ ( ˘︹˘ )"))
        except discord.Forbidden:
            raise UserWarning("ไม่มีสิทธิ์", "หนูไม่มีสิทธิ์เตะคนนี้นะคะ สิทธิ์ของเขาอาจจะสูงกว่าหนู (；￣Д￣)")
        except Exception as e:
            logger.error(f"Error kicking {member} from VC: {e}")
            raise UserError("เกิดข้อผิดพลาด", "เตะไม่สำเร็จค่ะ เซนเซย์ลองอีกรอบนะคะ")

def setup(bot: discord.Bot):
    bot.add_cog(VoiceKickCog(bot))
