import discord
from discord.ext import commands
from discord import app_commands

class Help(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Help cog loaded")

    @app_commands.command(name="help", description="❔ ความช่วยเหลือ")
    async def help(self, interaction: discord.Interaction):
        await self.log_cog.sendlog(interaction)
    
        # Embed
        util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
        util.add_field(name="**⏳ วัดความเร็วในการตอบสนองของบอท**", value="`/ping`", inline=True)
        util.add_field(name="**🔌 นับถอยหลังและเตะทุกคนออกจากแชทเสียง**", value="`/countdis`", inline=True)
        util.add_field(name="**🎙️ ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=True)
        util.add_field(name="**📨 ส่งข้อความผ่านบอท**", value="`/send`", inline=True)
        util.add_field(name="**🦵 เตะใครบางคนออกจากแชทเสียง**", value="`/kick`", inline=True)
        util.add_field(name="**📢 สแปมเรียกคนไม่เข้าประชุม**", value="`/spam`", inline=True) 
        util.add_field(name="**📝 เช็คชื่อผู้เข้าประชุมในแชทเสียง**", value="`/attendance`", inline=True)
        util.add_field(name="**😶‍🌫️ เช็คชื่อผู้ขาดการเข้าประชุมในแชทเสียง**", value="`/absent`", inline=True)
        util.add_field(name="**🎬 ดูข้อมูลคลิปวิดีโอจาก Youtube**", value="`/youtube`", inline=True)
        util.add_field(name="**🗞️ ดูบันทึกประวัติการส่งข้อความ**", value="`/getchat`", inline=True)
        util.add_field(name="**🧠 เปิด/ปิดการคุยกับบอท**", value="`/ai`", inline=True)
        util.add_field(name="**👤 ดูข้อมูลบัญชีของผู้ใช้**", value="`/user`", inline=True)
        util.add_field(name="**😂 สุ่มวิดีโอมีม**", value="`/meme`", inline=True)
        util.add_field(name="**📏 ปรับขนาดภาพ**", value="`/scale`", inline=True)
        util.add_field(name="**🐶 ตบหลังลูบหัว**", value="`/pet`", inline=True)
        util.add_field(name="**📸 QR Code Generator**", value="`/qr`", inline=True)
        util.add_field(name="**🎵 สร้างคลิปเสียงจากภาพ**", value="`/imgaudio`", inline=True)

        ai = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🧠 Ai*", color=0xfb17ff)
        ai.add_field(name="**⌨ แชทกับบอท**", value="`/ai chat `", inline=True)
        ai.add_field(name="**💹 แชทแบบไม่เก็บประวัติ** *(ประหยัดค่า API ;-;)*", value="`/ai oneshot-chat`", inline=True)
        ai.add_field(name="**🔊 พิมพ์แชทและฟังบอทพูด**", value="`/ai speak`", inline=True)
        ai.add_field(name="**🚮 ล้างประวัติการแชท**", value="`/ai reset`", inline=True)
        ai.add_field(name="**❌ ปิดการคุยกับบอท**", value="`/ai stop`", inline=True)

        contextmenu = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🖱️ Apps (Context Menu)*", color=0x2cd453)
        contextmenu.add_field(name="**🔎 ค้นหาด้วยรูปภาพ**", value="`Search by Image`", inline=True)
        contextmenu.add_field(name="**🍟 ทอดกรอบภาพ**", value="`Deepfry`", inline=True)
        contextmenu.add_field(name="**↔️ ยืดภาพ**", value="`Wide`", inline=True)
        contextmenu.add_field(name="**🖼️ ทำภาพขาวดำ**", value="`Grayscale`", inline=True)
        contextmenu.add_field(name="**ℹ️ ดูข้อมูลภาพ**", value="`Image Info`", inline=True)

        bugs = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *⚠️ ปัญหา*", color=0xff6c17)
        bugs.add_field(name="**มี...แต่ยังไม่แก้**", value="<a:VeryFunny:1244026451288657951>", inline=True)

        update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัปเดต*", color=0xdcfa80)
        update.add_field(name="1️⃣ V 2.0 | 04/12/2023", value="• Migrate from 1.x to 2.x\n• Rebuilt into a new bot structure", inline=True)
        update.add_field(name="2️⃣ V 2.1 | \*\*/\*\*/\*\*\*\*", value="• Improve overall performance", inline=True)

        select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
        discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
        discord.SelectOption(label="Ai", emoji="🧠",description="คุยกับบอท",value="ai",default=False),
        discord.SelectOption(label="Apps",emoji="🖱️",description="คำสั่งที่ใช้งานผ่านการ คลิกขวาที่ข้อความ -> Apps",value="contextmenu",default=False),
        discord.SelectOption(label="ปัญหา",emoji="⚠️",description="ปัญหาที่ทราบแล้ว",value="bugs",default=False),
        discord.SelectOption(label="ประวัติการอัปเดต",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
        ])

        async def my_callback(interaction):
            if select.values[0] == "util":
                await interaction.response.edit_message(embed=util, view=view)

            elif select.values[0] == "ai":
                await interaction.response.edit_message(embed=ai, view=view)

            elif select.values[0] == "contextmenu":
                await interaction.response.edit_message(embed=contextmenu, view=view)

            elif select.values[0] == "bugs":
               await interaction.response.edit_message(embed=bugs, view=view)

            elif select.values[0] == "update":
                await interaction.response.edit_message(embed=update, view=view)

        select.callback = my_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message(embed=util, view=view)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        
async def setup(client):
    print("Setting up Help cog")
    await client.add_cog(Help(client))