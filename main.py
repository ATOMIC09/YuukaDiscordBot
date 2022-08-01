import discord
from discord import app_commands, ui
import os
import asyncio 
from utils import countdown_fn

MY_GUILD = discord.Object(id=981567258222555186) #CPRE 981567258222555186 # TESTER 720687175611580426

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await client.change_presence(activity=discord.Game(name="💤 Standby..."))
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------------------------------------------------')

    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)

intents = discord.Intents.all()
intents.members = True
client = MyClient(intents=intents)

class SendLog():
    def __init__(self, interaction, val1):
        self.interaction = interaction
        if val1 == 0:
            self.val1 = ""
        else:
            self.val1 = val1

    async def send(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิรฟ์เวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```/{self.interaction.command.name} {self.val1}```")

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        
        await channel.send(embed=log,view=url_view)


################################################# Help #################################################
@client.tree.command(description="❔ ความช่วยเหลือ")
async def help(interaction: discord.Interaction):
    
    await SendLog.send(self=SendLog(interaction,0))
    # หน้าเมนู Embed
    util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
    util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=False)

    update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัพเดท*", color=0xdcfa80)
    update.add_field(name="1️⃣ V 1.0 | 29/07/2022", value="• Add: Countdis\n• Add: feedback")
    update.add_field(name="1️⃣ V 1.1 | 02/08/2022", value="• Add: Log\n• Improve: Embed Feedback")

    select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
    discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
    discord.SelectOption(label="ประวัติการอัพเดท",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
    ])

    async def my_callback(interaction):
        if select.values[0] == "util":
            await interaction.response.edit_message(embed=util)

        elif select.values[0] == "update":
            await interaction.response.edit_message(embed=update)
            
    select.callback = my_callback
    view = discord.ui.View()
    view.add_item(select)

    await interaction.response.send_message(embed=util, view=view)


################################################# Countdis #################################################
client.timestop = 0
client.member_except = []

@client.tree.command(description="⏱️ นับถอยหลังและตัดการเชื่อมต่อ")
@app_commands.describe(time="ใส่เวลาเป็นหน่วยวินาที")
async def countdis(interaction: discord.Interaction, time: str):
    await SendLog.send(self=SendLog(interaction,time))
    people_counter = 0

    time_int = int(time)
    client.timestop = time_int

    if time_int < 0:
        await interaction.response.send_message("**เวลาไม่ถูกต้อง ❌**")
    else:
        output = countdown_fn.countdown_fn(time_int)
        await interaction.response.send_message(output)
        for i in range(time_int):
            output = countdown_fn.countdown_fn(time_int)
            await interaction.edit_original_message(content=output)
            await asyncio.sleep(1)
            time_int -= 1

            if client.timestop == -22052603:
                await interaction.edit_original_message(content="**การนับถอยหลังถูกยกเลิก 🛑**")
                break
        if client.timestop != -22052603:
            try:
                members = interaction.user.voice.channel.members
                channel = interaction.user.voice.channel
            
                await interaction.edit_original_message(content="**หมดเวลา 🔔**")
                
                if client.member_except == []: # ไม่มีใครยกเว้น
                    members = interaction.user.voice.channel.members
                    for member in members:
                        await member.move_to(None)
                        people_counter += 1

                    client.member_except = []
                    await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อจำนวน {people_counter} คน จาก `{channel}` สำเร็จแล้ว**")

                else:
                    members = interaction.user.voice.channel.members
                    for member in members:
                        if member not in client.member_except: # เช็คว่าใครไม่ออก
                            await member.move_to(None)
                            people_counter += 1

                    await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อจำนวน {people_counter} คน จาก `{channel}` สำเร็จแล้ว**")
                    
            except:
                await interaction.edit_original_message(content="**ไม่เข้าห้องเสียงแล้วจะให้ถีบยังไงอะ (●'◡'●)**")


################################################# Except #################################################
client.last_use = [0]

@client.tree.command(name="except",description="⛔ ยกเว้นคำสั่ง Countdis")
async def except_def(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction,0))
    user = interaction.user
    if user.id not in client.last_use:
        client.member_except.append(user) # คนที่จะไม่ออก
        client.last_use.pop(0)
        client.last_use.append(user.id)
        await interaction.response.send_message(content=f"**<@{user.id}> ได้รับการยกเว้น <:Approve:921703512382009354>**")
    else:
        client.member_except.remove(user) # คนที่จะไม่ออก
        client.last_use.pop(0)
        client.last_use.append(0)
        await interaction.response.send_message(content=f"**<@{user.id}> ถูกลบออกจากรายการที่ยกเว้น <:Deny:921703523111022642>**")


################################################# Feedback #################################################
class FeedbackModal(ui.Modal, title='มีอะไรอยากบอก?'):
    message = ui.TextInput(label='Answer', style=discord.TextStyle.paragraph)
    
    async def on_submit(self, interaction: discord.Interaction):
        channel = client.get_channel(1002616395495907328)
        await interaction.response.send_message(f'ส่งข้อความเรียบร้อย ✅', ephemeral=True)
        feedback = discord.Embed(title="**📨 Feedback**", color=0x45E2A4)
        feedback.set_author(name=interaction.user, icon_url=interaction.user.display_avatar.url)
        feedback.timestamp = interaction.created_at
        feedback.add_field(name="เซิรฟ์เวอร์",value=f"`{interaction.guild}` ({interaction.guild_id})")
        feedback.add_field(name="ช่อง",value=f"`{interaction.channel}` ({interaction.channel_id})")
        feedback.add_field(name="ผู้เขียน",value=f"`{interaction.user}` ({interaction.user.id})")
        feedback.add_field(name="เนื้อหา",value=f"```{self.message}```")
        await channel.send(embed=feedback)

@client.tree.command(name="feedback",description="📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง")
async def feedback(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction,0))
    await interaction.response.send_modal(FeedbackModal())


Token = os.environ['YuukaToken']
client.run(Token)