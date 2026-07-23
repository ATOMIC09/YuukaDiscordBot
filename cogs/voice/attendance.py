import discord
from discord.ext import commands
import csv
import io
from datetime import datetime
import pytz

from bot.logger import logger
from utils.embeds import build_embed
from utils.errors import UserError

class AttendanceCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="attendance", description="📝 บันทึกการเข้าประชุม (เช็คชื่อคนในห้องเสียง)")
    async def attendance(self, ctx: discord.ApplicationContext):
        # 1. Check if user is in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", "คุณต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้นะคะ เซนเซย์ ┐( ˘_˘)┌")

        vc = ctx.author.voice.channel
        await ctx.defer()
        
        # 2. Gather non-bot members
        members = [m for m in vc.members if not m.bot]
        count = len(members)
        
        member_list_text = ""
        for m in members:
            member_list_text += f"> {m.display_name}\n"
            
        if not member_list_text:
            member_list_text = "-"
            
        # 3. Create CSV in memory
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        
        # Header
        csv_writer.writerow([f"บันทึกการเข้าประชุม {vc.name}"])
        csv_writer.writerow(["Number", "Display Name", "Username", "User ID", "Top Role", "Joined Server At", "Activity"])
        
        # Data
        for i, m in enumerate(members, 1):
            activity_name = m.activity.name if m.activity else "-"
            top_role = m.top_role.name if m.top_role else "-"
            joined_at = m.joined_at.strftime('%Y-%m-%d %H:%M:%S') if m.joined_at else "-"
            csv_writer.writerow([i, m.display_name, str(m.name), str(m.id), top_role, joined_at, activity_name])
            
        # Footer
        csv_writer.writerow([])
        tz = pytz.timezone('Asia/Bangkok')
        now_str = datetime.now(tz).strftime('%H:%M:%S')
        csv_writer.writerow([f"Time: {now_str}"])
        csv_writer.writerow([f"Executed by {ctx.author.display_name}"])
        
        # 4. Convert to BytesIO with utf-8-sig for Excel compatibility
        file_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8-sig'))
        file = discord.File(fp=file_bytes, filename=f"attendance_{vc.id}.csv")
        
        # 5. Build embed
        embed = build_embed(
            title="📝 บันทึกการเข้าประชุม",
            color=0x0A50C8
        )
        embed.timestamp = datetime.now(pytz.utc)
        embed.add_field(name="🔊 ช่องเสียง", value=f"`{vc.name}`", inline=False)
        embed.add_field(name="👥 จำนวนผู้เข้าร่วม", value=f"`{count} คน`", inline=False)
        
        if len(member_list_text) > 1024:
            member_list_text = member_list_text[:1020] + "..."
            
        embed.add_field(name="👤 รายชื่อ", value=member_list_text, inline=False)
        
        await ctx.respond(embed=embed)
        await ctx.followup.send(file=file)
        logger.info(f"Attendance recorded for {vc.name} by {ctx.author.display_name}")

    @discord.slash_command(name="absent", description="🔎 หาผู้ขาดการประชุม (ไม่ได้อยู่ในห้องเสียง)")
    async def absent(self, ctx: discord.ApplicationContext, role: discord.Option(discord.Role, "เลือกยศ/Role ที่ต้องการตรวจ (เว้นว่างเพื่อตรวจทั้งเซิร์ฟเวอร์)", required=False) = None): # type: ignore
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("ไม่ได้อยู่ในห้องเสียง", "คุณต้องอยู่ในห้องเสียงก่อน ถึงจะหาคนขาดได้นะคะ เซนเซย์ ಠ_ಠ")
            
        vc = ctx.author.voice.channel
        await ctx.defer()
        
        absent_members = []
        
        for member in ctx.guild.members:
            if member.bot:
                continue
                
            # Filter by role if provided
            if role and role not in member.roles:
                continue
                
            # Check if they are absent from this VC
            if not member.voice or member.voice.channel != vc:
                absent_members.append(member)
                
        count = len(absent_members)
        
        member_list_text = ""
        for m in absent_members:
            member_list_text += f"> {m.display_name}\n"
            
        if not member_list_text:
            member_list_text = "-"
            
        # Create CSV in memory
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        
        csv_writer.writerow([f"บันทึกการขาดประชุม {vc.name}"])
        csv_writer.writerow(["Number", "Display Name", "Username", "User ID", "Top Role", "Joined Server At", "Queried Role"])
        
        for i, m in enumerate(absent_members, 1):
            queried_role_name = role.name if role else "-"
            top_role = m.top_role.name if m.top_role else "-"
            joined_at = m.joined_at.strftime('%Y-%m-%d %H:%M:%S') if m.joined_at else "-"
            csv_writer.writerow([i, m.display_name, str(m.name), str(m.id), top_role, joined_at, queried_role_name])
            
        csv_writer.writerow([])
        tz = pytz.timezone('Asia/Bangkok')
        now_str = datetime.now(tz).strftime('%H:%M:%S')
        csv_writer.writerow([f"Time: {now_str}"])
        csv_writer.writerow([f"Executed by {ctx.author.display_name}"])
        
        file_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8-sig'))
        file = discord.File(fp=file_bytes, filename=f"absent_{vc.id}.csv")
        
        embed = build_embed(
            title="📝 บันทึกการขาดประชุม",
            color=0xFF3C5B
        )
        embed.timestamp = datetime.now(pytz.utc)
        if role:
            embed.add_field(name="🎩 บทบาท", value=f"`{role.name}`", inline=False)
            
        embed.add_field(name="🔊 ช่องเสียง", value=f"`{vc.name}`", inline=False)
        embed.add_field(name="👥 จำนวนผู้ขาด", value=f"`{count} คน`", inline=False)
        
        if len(member_list_text) > 1024:
            member_list_text = member_list_text[:1020] + "..."
            
        embed.add_field(name="👤 รายชื่อ", value=member_list_text, inline=False)
        
        await ctx.respond(embed=embed)
        await ctx.followup.send(file=file)
        logger.info(f"Absent recorded for {vc.name} by {ctx.author.display_name}")

def setup(bot: discord.Bot):
    bot.add_cog(AttendanceCog(bot))
