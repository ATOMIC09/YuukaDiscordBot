import discord
from discord.ext import commands
from bot.logger import logger
from bot.config import config
from utils.embeds import success_embed
from utils.errors import UserError
import pkgutil
from pathlib import Path

class AdminCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="reload", description="🔄️ โหลดโค้ดส่วนต่าง ๆ ใหม่")
    async def reload(self, ctx: discord.ApplicationContext):
        if not config.owner_id or ctx.author.id != config.owner_id:
            raise UserError("ไม่มีสิทธิ์", "หนูรับคำสั่งนี้จากเซนเซย์ที่เป็นเจ้าของเท่านั้นนะคะ! ಠ_ಠ")
            
        await ctx.defer(ephemeral=True)
        
        reloaded = []
        failed = []
        
        def reload_recursive(path: Path, package_prefix: str):
            for finder, name, is_pkg in pkgutil.iter_modules([str(path)]):
                full_name = f"{package_prefix}.{name}"
                if is_pkg:
                    reload_recursive(path / name, package_prefix=full_name)
                else:
                    try:
                        self.bot.reload_extension(full_name)
                        reloaded.append(full_name)
                    except Exception as e:
                        logger.error(f"Failed to reload cog {full_name}: {e}")
                        failed.append(f"`{full_name}`")
                        
        cogs_path = Path(__file__).parent.parent.parent / "cogs"
        reload_recursive(cogs_path, "cogs")
        
        if failed:
            raise UserError(
                "มีบางส่วนโหลดไม่ผ่านค่ะ",
                f"**โหลดผ่าน ({len(reloaded)} ระบบ)**\n**โหลดไม่ผ่าน ({len(failed)} ระบบ):** {', '.join(failed)}\nไปเช็คในคอนโซลดูนะคะ (；￣Д￣)"
            )
            
        await ctx.followup.send(embed=success_embed("โหลดระบบใหม่สำเร็จ!", f"โหลด `{len(reloaded)}` ระบบเสร็จเรียบร้อยค่ะ เซนเซย์ (๑>◡<๑)"))

def setup(bot: discord.Bot):
    bot.add_cog(AdminCog(bot))
