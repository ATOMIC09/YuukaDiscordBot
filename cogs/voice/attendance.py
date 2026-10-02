import discord
from discord.ext import commands

from bot.logger import logger
from utils.attendance import absent_report, attendance_report
from utils.errors import UserError


class AttendanceCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="attendance", description="📝 บันทึกการเข้าประชุม (เช็คชื่อคนในห้องเสียง)")
    async def attendance(self, ctx: discord.ApplicationContext):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", "คุณต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้นะคะ เซนเซย์ ┐( ˘_˘)┌")

        vc = ctx.author.voice.channel
        await ctx.defer()

        report = attendance_report(vc, ctx.author.display_name)
        await ctx.respond(embed=report.embed)
        await ctx.followup.send(file=report.file)
        logger.info(f"Attendance recorded for {vc.name} by {ctx.author.display_name}")

    @discord.slash_command(name="absent", description="🔎 หาผู้ขาดการประชุม (ไม่ได้อยู่ในห้องเสียง)")
    async def absent(self, ctx: discord.ApplicationContext, role: discord.Option(discord.Role, "เลือกยศ/Role ที่ต้องการตรวจ (เว้นว่างเพื่อตรวจทั้งเซิร์ฟเวอร์)", required=False) = None): # type: ignore
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", "คุณต้องอยู่ในห้องเสียงก่อน ถึงจะหาคนขาดได้นะคะ เซนเซย์ ಠ_ಠ")

        vc = ctx.author.voice.channel
        await ctx.defer()

        report = absent_report(ctx.guild, vc, ctx.author.display_name, role)
        await ctx.respond(embed=report.embed)
        await ctx.followup.send(file=report.file)
        logger.info(f"Absent recorded for {vc.name} by {ctx.author.display_name}")


def setup(bot: discord.Bot):
    bot.add_cog(AttendanceCog(bot))
