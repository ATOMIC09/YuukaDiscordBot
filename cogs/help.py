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
        util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=True)
        util.add_field(name="**🎙️ ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=True)
        util.add_field(name="**📨 ส่งข้อความ**", value="`/send`", inline=True)
        util.add_field(name="**🦵 เตะคนออกจากแชทเสียง**", value="`/kick`", inline=True)
        util.add_field(name="**📢 สแปมคนไม่มา**", value="`/spam`", inline=True) 
        util.add_field(name="**🗞️ บันทึกประวัติการส่งข้อความ**", value="`/getchat`", inline=True)
        util.add_field(name="**📝 เช็คชื่อในช่องเสียง**", value="`/attendance`", inline=True)
        util.add_field(name="**😶‍🌫️ เช็คคนขาดประชุม**", value="`/absent`", inline=True)
        util.add_field(name="**👤 ดูข้อมูลของผู้ใช้**", value="`/user`", inline=True)
        util.add_field(name="**🍟 ทอดกรอบภาพ**", value="`/deepfry`", inline=True)
        util.add_field(name="**🧠 เปิด/ปิดการคุยกับบอท**", value="`/ai`", inline=True)
        util.add_field(name="**🎬 ขอไฟล์จาก Youtube**", value="`/youtube`", inline=True)
        util.add_field(name="**😂 สุ่มวิดีโอมีม**", value="`/meme`", inline=True)

        contextmenu = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🖱️ Apps (Context Menu)*", color=0x2cd453)
        contextmenu.add_field(name="**🔎 ค้นหาด้วยรูปภาพ**", value="`Search by Image`", inline=True)

        #unstable = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *⚠️ คำสั่งที่ยังไม่เสถียร*", color=0xff6c17)
        #unstable.add_field(name="****", value="`/youtube`", inline=True)

        update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัปเดต*", color=0xdcfa80)
        update.add_field(name="1️⃣ V 1.0 | 29/07/2022", value="• Add: Countdis command (countdown and disconnect all user in voice channel)\n• Add: Feedback")
        update.add_field(name="2️⃣ V 1.1 | 02/08/2022", value="• Add: Log\n• Add: Youtube\n• Add: Search by Image\n• Add: AutoDelete Temp\n• Add: Hosting Status\n• Improve: Embed Feedback")
        update.add_field(name="3️⃣ V 1.2 | 02/09/2022", value="• Add: Send command\n• Add: Kick member from voice chat")
        update.add_field(name="4️⃣ V 1.3 | 02/10/2022", value="• Add: Deepfry command\n• Change: Private command to Global Command")
        update.add_field(name="5️⃣ V 1.4 | 11/10/2022", value="• Add: Spam Mentions")
        update.add_field(name="6️⃣ V 1.5 | 24/10/2022", value="• Add: Announcement(For Bot Admin Only)\n• Add: Attendance\n• Add: Absent\n• Add: Cancel\n• Hotfix: Spam Mentions")
        update.add_field(name="7️⃣ V 1.6 | 14/12/2022", value="• Add: AI\n• Change: Emoji and Decoration")
        update.add_field(name="8️⃣ V 1.7 | 22/02/2023", value="• Fix: The AI has pre-trained data and Chat without using the slash command.\n• Change: Fully open public bots. Cancel and Except is combined with the Countdis command and optimize some operations")
        update.add_field(name="9️⃣ V 1.8 | 14/03/2023", value="• Add: AI that powered by GPT-3.5 Turbo from OpenAI\n• Add: \"I can speak English, Thai, and Japanese right now! or you can use custom language code as well. But still can't listen to you :(\"\n• Remove: ChatterBot training menu")
        update.add_field(name="🔟 V 1.9 | 08/04/2023", value="• Add: User command for checking profile and status\n• Add: Split the message by | instead of \\n and make the prompt more human-like and make a reset button for chat. And getchat download is now available\n• Add: Random meme generator")

        select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
        discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
        discord.SelectOption(label="Apps",emoji="🖱️",description="คำสั่งที่ใช้งานผ่านการ คลิกขวาที่ข้อความ -> Apps",value="contextmenu",default=False),
        #discord.SelectOption(label="คำสั่งที่ยังไม่เสถียร",emoji="⚠️",description="คำสั่งที่ยังไม่เสถียร",value="unstable",default=False),
        discord.SelectOption(label="ประวัติการอัปเดต",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
        ])

        async def my_callback(interaction):
            if select.values[0] == "util":
                await interaction.response.edit_message(embed=util, view=view)

            elif select.values[0] == "contextmenu":
                await interaction.response.edit_message(embed=contextmenu, view=view)

            #elif select.values[0] == "unstable":
            #    await interaction.response.edit_message(embed=unstable, view=view)

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