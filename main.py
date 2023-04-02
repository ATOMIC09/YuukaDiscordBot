# Rebuild in v2.0
import discord
from discord import app_commands, ui
from discord.ext import tasks
import os
import asyncio 
from utils import countdown_fn, youtubedl_fn, sectobigger, shorten_url, imageprocess_fn, filesize, chatgpt, speech_synthesis, tts_language_check
import requests
import shutil
import json
import psutil
import csv
import pytz
from pyexcel.cookbook import merge_all_to_a_book
import glob
from typing import Optional
import time

class MyClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.countdis_except = {}
        self.time_stop = {}
        self.last_image = {}
        self.last_image_url = {}
        self.last_video = {}
        self.last_video_url = {}
        self.last_audio = {}
        self.last_audio_url = {}
        self.last_pdf = {}
        self.last_pdf_url = {}
        self.name_only = {}
        self.stopSpam = {}
        self.force_stop = {}
        self.overtime = {}
        self.talk_to_ai = {}
        self.ai_active_channel = {}
        self.chat_history = {}
        self.voice = {}
        self.voice_language = {}

    async def on_ready(self):
        if not host_status_change.is_running():
            host_status_change.start()
        if not autodelete.is_running():
            autodelete.start()
        await self.setup_hook()
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------------------------------------------------')

    async def setup_hook(self):
        #MY_GUILD = discord.Object(id=720687175611580426)  
        await self.tree.sync()

class InfomationLog():
    def __init__(self, interaction="", log_data="", message=None):
        self.interaction = interaction
        self.log_data = log_data
        self.message = message

    async def sendlog(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิร์ฟเวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="หมวดหมู่",value=f"`{self.interaction.channel.category.name}` ({self.interaction.channel.category.id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```/{self.interaction.command.name} {self.log_data}```")
        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        await channel.send(embed=log,view=url_view)
    
    async def contextlog(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิร์ฟเวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="หมวดหมู่",value=f"`{self.interaction.channel.category.name}` ({self.interaction.channel.category.id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```{self.interaction.command.name} กับรูปภาพ```")
        log.set_image(url=self.log_data.attachments[0])
        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        await channel.send(embed=log,view=url_view)
        
    async def openailog(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.message.id}`", color=0x11a37f)
        log.set_author(name=self.message.author, icon_url=self.message.author.display_avatar.url)
        log.timestamp = self.message.created_at
        log.add_field(name="Prompt",value=f"`{self.log_data['prompt']}`")
        log.add_field(name="Response",value=f"`{self.log_data['response']}`")
        log.add_field(name="Total Tokens", value=f"`{self.log_data['total_tokens']}`")
        log.add_field(name="Prompt Token", value=f"`{self.log_data['prompt_tokens']}`")
        log.add_field(name="Completion Token", value=f"`{self.log_data['completion_tokens']}`")
        log.add_field(name="Finish Reason", value=f"`{self.log_data['finish_reason']}`")
        log.add_field(name="Create", value=f"`{self.log_data['created']}`")
        log.add_field(name="id", value=f"`{self.log_data['id']}`")
        log.add_field(name="Model", value=f"`{self.log_data['model']}`")
        log.add_field(name="Object", value=f"`{self.log_data['object']}`")
        log.add_field(name="Chat History", value=f"```{self.log_data['chat_history']}```")
        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.message.guild.id}/{self.message.channel.id}/{self.message.id}"))
        await channel.send(embed=log,view=url_view)

intents = discord.Intents.all()
intents.members = True
client = MyClient(intents=intents)
client.IsAnnouncement = False
client.first_yuuka_prompt = "Yuuka: My Fullname is Hayase Yuuka, So let's call it Yuuka for short. (from Blue Archive). She is a 16-year-old mathematical genius and treasurer at the Millennium Science School. She has a calm and professional demeanor, but can be strict with money. In combat, she is a Tank/Front with an Explosive damage type and Heavy armor. Her appearance includes navy blue hair tied in pigtails, bright blue eyes, and a standard uniform with black guns. (Doing human-like as well and don't ever mention about AI or language model. You will talk to many people with different name because you are in a group chat. Username is in front of the sentence. And you can talk to everything because you are know everything.)"

@client.tree.command(name='help', description='❔ ความช่วยเหลือ')
async def help(interaction: discord.Interaction):
    await InfomationLog.sendlog(self=InfomationLog(interaction))
    
    # Embed
    util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
    util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=False)
    util.add_field(name="**📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=False)
    util.add_field(name="**🎬 ขอไฟล์จาก Youtube**", value="`/youtube`", inline=False)
    util.add_field(name="**📨 ส่งข้อความ**", value="`/send`", inline=False)
    util.add_field(name="**🦵 เตะคนออกจากแชทเสียง**", value="`/kick`", inline=False)
    util.add_field(name="**🍟 ทอดกรอบภาพ**", value="`/deepfry`", inline=False)
    util.add_field(name="**📢 สแปมคนไม่มา**", value="`/spam`", inline=False) 
    util.add_field(name="**📝 เช็คชื่อในช่องเสียง**", value="`/attendance`", inline=False)
    util.add_field(name="**🔎 เช็คคนขาดประชุม**", value="`/absent`", inline=False)

    ai = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🤖 Artificial Intelligence*", color=0x03dffc)
    ai.add_field(name="**🧠 เปิด/ปิดการคุยกับบอท**", value="`/ai`", inline=False)
    ai.add_field(name="**🗞️ บันทึกประวัติการส่งข้อความ**", value="`/getchat`", inline=False)

    update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัพเดท*", color=0xdcfa80)
    update.add_field(name="1️⃣ V 1.0 | 29/07/2022", value="• Add: Countdis command (countdown and disconnect all user in voice channel)\n• Add: Feedback")
    update.add_field(name="2️⃣ V 1.1 | 02/08/2022", value="• Add: Log\n• Add: Youtube\n• Add: Search by Image\n• Add: AutoDelete Temp\n• Add: Hosting Status\n• Improve: Embed Feedback")
    update.add_field(name="3️⃣ V 1.2 | 02/09/2022", value="• Add: Send command\n• Add: Kick member from voice chat")
    update.add_field(name="4️⃣ V 1.3 | 02/10/2022", value="• Add: Deepfry command\n• Change: Private command to Global Command")
    update.add_field(name="5️⃣ V 1.4 | 11/10/2022", value="• Add: Spam Mentions")
    update.add_field(name="6️⃣ V 1.5 | 24/10/2022", value="• Add: Announcement(For Bot Admin Only)\n• Add: Attendance\n• Add: Absent\n• Add: Cancel\n• Hotfix: Spam Mentions")
    update.add_field(name="7️⃣ V 1.6 | 14/12/2022", value="• Add: AI\n• Change: Emoji and Decoration")
    update.add_field(name="8️⃣ V 1.7 | 22/02/2023", value="• Fix: The AI has pre-trained data and Chat without using the slash command.\n• Change: Fully open public bots. Cancel and Except is combined with the Countdis command and optimize some operations")
    update.add_field(name="9️⃣ V 1.8 | 14/03/2023", value="• Add: AI that powered by GPT-3.5 Turbo from OpenAI\n• Add: I can speak English, Thai, and Japanese right now! or you can use custom language code as well. But still can't listen to you :(\n• Remove: ChatterBot training menu")
    update.add_field(name="🔟 V ??? | TBA", value="• Add: Guild, User, Stats Information")

    select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
    discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
    discord.SelectOption(label="Artificial Intelligence",emoji="🤖",description="คำสั่งเกี่ยวกับ AI ของบอท",value="ai",default=False),
    discord.SelectOption(label="ประวัติการอัพเดท",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
    ])

    async def my_callback(interaction):
        if select.values[0] == "util":
            await interaction.response.edit_message(embed=util, view=view)

        elif select.values[0] == "update":
            await interaction.response.edit_message(embed=update, view=view)

        elif select.values[0] == "ai":
            await interaction.response.edit_message(embed=ai, view=view)

    select.callback = my_callback
    view = discord.ui.View()
    view.add_item(select)
    await interaction.response.send_message(embed=util, view=view)


@client.tree.command(name='countdis', description='🔌 นับถอยหลังและตัดการเชื่อมต่อ')
@app_commands.describe(time='เวลาเป็นหน่วยวินาที')
async def countdis(interaction: discord.Interaction, time: int):
    try:
        all_member = interaction.user.voice.channel.members
        await InfomationLog.sendlog(self=InfomationLog(interaction, str(time)))

        stop_button = discord.ui.Button(label="Stop", style=discord.ButtonStyle.red)
        exceptme_button = discord.ui.Button(label="Except Me", style=discord.ButtonStyle.primary)
        guild = interaction.guild_id
        channel = interaction.user.voice.channel
        member_count = 0

        if guild not in client.time_stop:
            client.time_stop[guild] = False
        if guild not in client.countdis_except: 
            client.countdis_except[guild] = []
        
        if time < 0:
            await interaction.response.send_message("**เวลาไม่ถูกต้อง ❌**")
        else:
            output = countdown_fn.countdown_fn(time)
            view = discord.ui.View()
            view.add_item(stop_button)
            view.add_item(exceptme_button)

            await interaction.response.send_message(output, view=view)
            for i in range(time):
                if client.time_stop[guild] == True:
                    await interaction.edit_original_response(content="**ยกเลิกการนับถอยหลังแล้ว 🛑**", view=None)
                    break
                await asyncio.sleep(1)
                output = countdown_fn.countdown_fn(time - i - 1)
                await interaction.edit_original_response(content=output)

                # Except Me
                async def exceptme(interaction: discord.Interaction):
                    if interaction.user.id in client.countdis_except[guild]:
                        client.countdis_except[guild].remove(interaction.user.id)
                        await interaction.response.send_message(content=f"**<@{interaction.user.id}> ไม่ถูกยกเว้นแล้ว ❌**")
                    else:
                        client.countdis_except[guild].append(interaction.user.id)
                        await interaction.response.send_message(content=f"**<@{interaction.user.id}> ถูกยกเว้นแล้ว ✅**")
                
                async def stop(interaction: discord.Interaction):
                    client.time_stop[guild] = True
                stop_button.callback = stop
                exceptme_button.callback = exceptme

            if client.time_stop[guild] == False:
                await interaction.edit_original_response(content="**หมดเวลา 🔔**", view=None)
                for member in all_member:
                    if member.id in client.countdis_except[guild]:
                        continue
                    await member.move_to(None)
                    member_count += 1
                
                await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อจำนวน {member_count} คน จาก `{channel}` สำเร็จแล้ว**")

            # Reset
            client.countdis_except[guild] = []
            client.time_stop[guild] = False
    
    except AttributeError:
        await interaction.response.send_message(content="**ถีบใคร? ไม่มีใครให้ถีบอะดิ (●'◡'●)**")

@client.tree.command(name='send', description="📨 ส่งข้อความด้วยบอท")
@app_commands.describe(channel="ช่องข้อความที่จะส่ง",message="ข้อความ")
async def send(interaction: discord.Interaction, channel: discord.TextChannel, *, message: str):
    combine_arg = str(channel.id) + " " + message
    await InfomationLog.sendlog(self=InfomationLog(interaction,combine_arg))
    await interaction.response.send_message(f'"{message}" ถูกส่งไปยัง {channel.mention}',ephemeral=True)
    await channel.send(message)

@client.tree.command(name='kick', description="🦵 เตะสมาชิกจากช่องเสียง")
@app_commands.describe(member="ผู้ใช้")
async def kick(interaction: discord.Interaction, member: discord.Member):
    await InfomationLog.sendlog(self=InfomationLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    await interaction.response.send_message(f'<@{member.id}> ถูกเตะออกจาก `{member.voice.channel}`',ephemeral=True)
    await member.move_to(None)


class FeedbackModal(ui.Modal, title='มีอะไรอยากบอก?'):
    message = ui.TextInput(label='Answer', style=discord.TextStyle.paragraph)
    
    async def on_submit(self, interaction: discord.Interaction):
        channel = client.get_channel(1002616395495907328)
        await interaction.response.send_message(f'ส่งข้อความเรียบร้อย ✅', ephemeral=True)
        feedback = discord.Embed(title="**📨 Feedback**", color=0x45E2A4)
        feedback.set_author(name=interaction.user, icon_url=interaction.user.display_avatar.url)
        feedback.timestamp = interaction.created_at
        feedback.add_field(name="เซิร์ฟเวอร์",value=f"`{interaction.guild}` ({interaction.guild_id})")
        feedback.add_field(name="หมวดหมู่",value=f"`{interaction.channel.category.name}` ({interaction.channel.category.id})")
        feedback.add_field(name="ช่อง",value=f"`{interaction.channel}` ({interaction.channel_id})")
        feedback.add_field(name="ผู้เขียน",value=f"`{interaction.user}` ({interaction.user.id})")
        feedback.add_field(name="เนื้อหา",value=f"```{self.message}```")
        await channel.send(embed=feedback)

@client.tree.command(name="feedback",description="📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง")
async def feedback(interaction: discord.Interaction):
    await InfomationLog.sendlog(self=InfomationLog(interaction))
    await interaction.response.send_modal(FeedbackModal())

@client.tree.command(name='deepfry', description="🍟 ทอดกรอบภาพ")
async def deepfry(interaction: discord.Interaction):
    guild = interaction.guild_id
    try:
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        shutil.copy(f"temp/autosave/{client.last_image[guild]}", f"asset/deepfry/deepfryer_input/{client.last_image[guild]}")
        imageprocess_fn.deepfry(f"asset/deepfry/deepfryer_input/{client.last_image[guild]}")
        await InfomationLog.sendlog(self=InfomationLog(interaction))

        if "_deepfryer" in client.name_only[guild]:
            path = f'asset/deepfry/deepfryer_output/{client.name_only[guild]}.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        else:
            path = f'asset/deepfry/deepfryer_output/{client.name_only[guild]}_deepfryer.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
    except KeyError:
        await interaction.edit_original_response(content="❌ **ไม่พบรูปภาพ**")

@client.tree.command(name='spam', description="📢 สแปมคนไม่มา")
@app_commands.describe(member="ผู้ใช้", message="ข้อความ", delay="การหน่วงเวลา", amount="จำนวนครั้ง")
async def spam(interaction: discord.Interaction, member: discord.Member, *, message: str, delay: int = 2, amount: int = 5):
    await InfomationLog.sendlog(self=InfomationLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    guild = interaction.guild_id
    client.stopSpam[guild] = False

    stop = discord.ui.Button(label="หยุดสแปม",emoji="⏹",style=discord.ButtonStyle.red)
    async def stop_callback(interaction):
        client.stopSpam[guild] = True

    stop.callback = stop_callback
    view = discord.ui.View()
    view.add_item(stop)
    await interaction.response.send_message(content=f'<a:LoadingGIF:1052561472263299133> **กำลังสแปม** {message} **กับ** <@{member.id}>',ephemeral=True,view=view)
    
    for i in range(amount):
        if client.stopSpam[guild] == False:
            await asyncio.sleep(delay)
            await interaction.followup.send(f'{message} <@{member.id}>')
        else:
            break
    if client.stopSpam[guild] == False:
        await interaction.edit_original_response(content=f'✅ **สแปม** {message} **กับ** <@{member.id}> **จบแล้ว**',view=None)    
    else:
        await interaction.edit_original_response(content=f'⛔ **หยุดสแปม** {message} **กับ** <@{member.id}> **แล้ว**',view=None)

@client.tree.command(name='announce', description="📢 ประกาศ (เฉพาะผู้ดูแล)")
@app_commands.describe(message="ข้อความประกาศ")
async def announce(interaction: discord.Interaction, *, message: str):
    if interaction.user.id == 269000561255383040:
        if client.IsAnnouncement == False:
            await InfomationLog.sendlog(self=InfomationLog(interaction, message))
            client.IsAnnouncement = True
            await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
            await interaction.response.send_message(f'✅ **ประกาศ** {message} **เรียบร้อย**',ephemeral=True)
        else:
            client.IsAnnouncement = False
            await interaction.response.send_message(f'⏹ **หยุดประกาศเรียบร้อย**',ephemeral=True)

@client.tree.command(name='attendance', description="📝 บันทึกการเข้าประชุม")
async def attendance(interaction: discord.Interaction):
    try:
        vc = interaction.user.voice.channel
        member = ""
        count = 0

        for user in vc.members:
            if user.bot == False:
                member += f'> {user.display_name}\n'
                count += 1

        await InfomationLog.sendlog(self=InfomationLog(interaction))
        log = discord.Embed(title="📝 บันทึกการเข้าประชุม",color=0x0A50C8)
        log.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
        log.add_field(name="👥 จำนวนผู้เข้าร่วม",value=f'`{count} คน`',inline=False)
        log.add_field(name="👤 รายชื่อ", value=f'{member}', inline=False)
        log.timestamp = interaction.created_at

        data = [[f"บันทึกการเข้าประชุม {vc.name}"]]
        data.append(["Number","Name","Discord Activity"])

        for i in range(count):
            try:
                activity = vc.members[i].activity.name
            except:
                activity = "-"

            data.append([i+1,vc.members[i].display_name,activity])
            
        data.append([""])
        data.append([f"Time: {interaction.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%H:%M:%S')}"])
        data.append([f"Executed by {interaction.user.display_name}"])

        # Crate CSV file
        with open(f'temp/{vc.id}_attend.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(data)

        # Create XLSX file
        merge_all_to_a_book(glob.glob(f"temp/{vc.id}_attend.csv"), f"temp/{vc.id}_attend.xlsx")

        # On Click Export
        get_csv = discord.ui.Button(label="Export to CSV",emoji="📤",style=discord.ButtonStyle.primary)
        get_xlsx = discord.ui.Button(label="Export to XLSX",emoji="📤",style=discord.ButtonStyle.green)

        async def get_csv_callback(interaction):
            try:
                file = discord.File(f"temp/{vc.id}_attend.csv")
                await interaction.response.send_message(file=file)
            except:
                await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

        async def get_xlsx_callback(interaction):
            try:
                file = discord.File(f"temp/{vc.id}_attend.xlsx")
                await interaction.response.send_message(file=file)
            except:
                await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

        get_csv.callback = get_csv_callback
        get_xlsx.callback = get_xlsx_callback
        view = discord.ui.View()
        view.add_item(get_csv)
        view.add_item(get_xlsx)
        await interaction.response.send_message(embed=log,view=view)

    except:
        await interaction.response.send_message(f"**คุณต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้ ┐⁠(⁠ ⁠˘⁠_⁠˘⁠)⁠┌**")

@client.tree.command(name='absent', description="🔎 หาผู้ขาดการประชุม")
@app_commands.describe(role="ใส่บทบาทที่ต้องการหาผู้ขาดการประชุม")
async def absent(interaction: discord.Interaction, role: Optional[discord.Role]):
    try:
        member_absent = ""
        count = 0
        vc = interaction.user.voice.channel

        data = [[f"บันทึกการขาดประชุม {vc.name}"]]
        data.append(["Number","Name","Role"])

        for member in interaction.guild.members:
            if member.voice == None:
                if role == None:
                    member_absent += f'> {member.display_name}\n'
                    count += 1
                    data.append([count,member.display_name,"-"])
                else:
                    if role in member.roles:
                        member_absent += f'> {member.display_name}\n'
                        count += 1
                        data.append([count,member.display_name,role.name])
        if role == None:
            await InfomationLog.sendlog(self=InfomationLog(interaction))
        else:
            await InfomationLog.sendlog(self=InfomationLog(interaction,role))
        
            data.append([""])
        data.append([f"Time: {interaction.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%H:%M:%S')}"])
        data.append([f"Executed by {interaction.user.display_name}"])

        # Crate CSV file
        with open(f'temp/{vc.id}_absent.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(data)

        # Create XLSX file
        merge_all_to_a_book(glob.glob(f"temp/{vc.id}_absent.csv"), f"temp/{vc.id}_absent.xlsx")

        # On Click Export
        get_csv = discord.ui.Button(label="Export to CSV",emoji="📤",style=discord.ButtonStyle.primary)
        get_xlsx = discord.ui.Button(label="Export to XLSX",emoji="📤",style=discord.ButtonStyle.green)

        async def get_csv_callback(interaction):
            try:
                file = discord.File(f"temp/{vc.id}_absent.csv")
                await interaction.response.send_message(file=file)
            except:
                await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

        async def get_xlsx_callback(interaction):
            try:
                file = discord.File(f"temp/{vc.id}_absent.xlsx")
                await interaction.response.send_message(file=file)
            except:
                await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

        get_csv.callback = get_csv_callback
        get_xlsx.callback = get_xlsx_callback
        view = discord.ui.View()
        view.add_item(get_csv)
        view.add_item(get_xlsx)

        if member_absent == "":
            member_absent = "-"

        if role == None:
            absent = discord.Embed(title="📝 บันทึกการขาดประชุม",color=0xFF3C5B)
            absent.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
            absent.add_field(name="👥 จำนวนผู้ขาด",value=f'`{count} คน`',inline=False)
            absent.add_field(name="👤 รายชื่อ", value=f'{member_absent}', inline=False)
            absent.timestamp = interaction.created_at
            await interaction.response.send_message(embed=absent,view=view)
        
        else:
            absent = discord.Embed(title="📝 บันทึกการขาดประชุม",color=0xFF3C5B)
            absent.add_field(name="🎩 บทบาท",value=f'`{role}`',inline=False)
            absent.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
            absent.add_field(name="👥 จำนวนผู้ขาด",value=f'`{count} คน`',inline=False)
            absent.add_field(name="👤 รายชื่อ", value=f'{member_absent}', inline=False)
            absent.timestamp = interaction.created_at
            await interaction.response.send_message(embed=absent,view=view)
    except:
        await interaction.response.send_message(f"**ต้องอยู่ในห้องเสียงก่อน ถึงจะหาคนขาดได้ ಠ⁠_⁠ಠ**")

@client.tree.command(name="youtube",description="🎬 ขอไฟล์จาก Youtube (Not functional)")
@app_commands.describe(url="ใส่ URL ของคลิปใน Youtube")
async def youtube_def(interaction: discord.Interaction, url: str):
    await InfomationLog.sendlog(self=InfomationLog(interaction,url))
    await interaction.response.send_message(f"<a:MagnifierGIF:1052563354910216252> **กำลังหา** `{url}`")

    # เก็บข้อมูลดิบ
    title = youtubedl_fn.yt_title(url)
    ext = youtubedl_fn.yt_ext(url)
    upload_date = youtubedl_fn.yt_upload_date(url)
    channel, channel_id = youtubedl_fn.yt_channel(url)
    duration = youtubedl_fn.yt_duration(url)
    view_count = youtubedl_fn.yt_view_count(url)
    try:
        like_count = youtubedl_fn.yt_like_count(url)
    except:
        like_count = "Null"
    dislike_count = youtubedl_fn.yt_dislike_count(url)
    comment_count = youtubedl_fn.yt_comment_count(url)
    filesize_approx = youtubedl_fn.yt_filesize_approx(url)

    # ข้อมูลสำคัญ
    videolink = youtubedl_fn.yt_video(url)
    audiolink = youtubedl_fn.yt_audio(url)
    thumbnail = youtubedl_fn.yt_thumbnail(url)

    # ข้อมูลสุก
    videolinknew = shorten_url.shortenmylink(videolink)
    audiolinknew = shorten_url.shortenmylink(audiolink)
    durationnew = sectobigger.sec(duration)
    upload_datenew = sectobigger.datenumbeautiful(upload_date)

    dl = discord.Embed(title = f"**{title}**", color = 0xff80c9)
    dl.timestamp = interaction.created_at
    dl.add_field(name="🔐 นามสกุลไฟล์", value=f"`{ext}`", inline=False)
    dl.add_field(name="🥼 ช่อง", value=f"`{channel}` `({channel_id})`", inline=False)
    dl.add_field(name="📆 วันที่อัพโหลด", value=f"`{upload_datenew}`", inline=False)
    dl.add_field(name="🕒 ระยะเวลา", value=f"`{durationnew}`", inline=False)
    dl.add_field(name="👀 จำนวนคนดู", value=f"`{view_count} คน`", inline=False)
    dl.add_field(name="👍🏻 จำนวนคน Like", value=f"`{like_count} คน`", inline=False)
    dl.add_field(name="👎🏻 จำนวนคน Dislike", value=f"`{dislike_count} คน`", inline=False)
    dl.add_field(name="💬 จำนวน Comment", value=f"`{comment_count} คน`", inline=False)
    dl.add_field(name="📦 ขนาดไฟล์", value=f"`{filesize_approx}`", inline=False)
    dl.set_image(url=thumbnail)

    url_view = discord.ui.View()
    url_view.add_item(discord.ui.Button(label='Video',emoji="🎬" , style=discord.ButtonStyle.url, url=videolinknew))
    url_view.add_item(discord.ui.Button(label='Audio',emoji="🔊" , style=discord.ButtonStyle.url, url=audiolinknew))

    await interaction.edit_original_response(content="",embed=dl,view=url_view)

@client.tree.command(name='getchat', description="🗞️ บันทึกประวัติการส่งข้อความ (Not functional)")
async def getchat(interaction: discord.Interaction):
    await InfomationLog.sendlog(self=InfomationLog(interaction))
    channel = interaction.channel
    start_time = time.time()
    guild = interaction.guild_id
    client.force_stop[guild] = False
    client.overtime[guild] = False
    channel_count = 0
    channel_total = len(interaction.guild.text_channels)
    await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> 0% กำลังเริ่มต้น...ตรวจพบ {channel_total} ช่อง**")

    # LOOP CHANNEL
    for channel in interaction.guild.text_channels:
        percent_total = round((channel_count / channel_total) * 100, 1)

        stop_button = discord.ui.Button(label="หยุด",emoji="❎",style=discord.ButtonStyle.red)
        
        async def stop_callback(interaction):
            client.force_stop[guild] = True

        stop_button.callback = stop_callback
        view = discord.ui.View()
        view.add_item(stop_button)


        start_save = time.time()
        start_channel_percent = time.time()
        percent_channel = 0
        msg_total = 0
        current_msg = 0

        # GET TOTAL MESSAGE IN CHANNEL
        async for _ in channel.history(limit=None):
            msg_total += 1

        # CHECK IF FILE ALREADY EXIST (SAME CHANNEL)
        if os.path.exists(f"asset/chat/{channel.id}.txt") == True:
            channel_left = channel_total - channel_count
            print(f"{percent_total}% ข้าม <#{channel.id}> ไปแล้ว (ไฟล์มีอยู่แล้ว)")
            #print(f'TIME TICK: {time.time() - start_channel_percent}')
            if time.time() - start_channel_percent > 1: # 1 Second
                await interaction.edit_original_response(content=f"**<a:AppleLoadingGIF:1052465926487953428> 0% กำลังเริ่มต้น...คงเหลือ {channel_left} ช่อง**")
            channel_count += 1
            continue
        else:
            print(f"ไม่พบไฟล์ <#{channel.id}> เริ่มการดึงข้อความจากช่องนี้")
        
        # LOOP MESSAGE (SAVE TO FILE)
        with open(f"asset/chat/{channel.id}.txt", "w", encoding="utf-8") as f:
            async for message in channel.history(limit=None):
                # BEFORE WRITE
                # SEND UPDATE PROGRESS (EVERY MORE THAN 1 SECOND)
                percent_channel = round((current_msg / msg_total) * 100, 1)
                #print(f'TIME TICK: {time.time() - start_channel_percent}')
                if time.time() - start_channel_percent > 1: # 1 Second
                    try:
                        elasp_time = time.time() - start_time
                        if time.time() - start_save < 840: # In 14 Minutes (840 Seconds)
                            print(f"{percent_total}% ดึงข้อความจาก <#{channel.id}> ไปแล้ว {percent_channel}%")
                            await interaction.edit_original_response(content=f"**<a:AppleLoadingGIF:1052465926487953428> {percent_total}% ดึงข้อความจาก <#{channel.id}> ไปแล้ว {percent_channel}% `{sectobigger.sec(elasp_time)}`**",view=view)
                            start_channel_percent = time.time()
                        else: # More than 14 Minutes
                            print(f"{percent_total}% ดึงข้อความเบื้องหลังจาก <#{channel.id}> ไปแล้ว {percent_channel}%")
                            await interaction.edit_original_response(content=f"**ℹ️ กำลังดึงข้อความในเบื้องหลัง...**",view=None)
                    except: # If interaction is timeout
                        print("Interaction is timeout")
                        client.overtime[guild] = True
                # WHILE WRITE
                    # f.write takes too much time for update progress in discord
                    # Means it will update every time a single line is written.
                f.write(f"{message.content}\n") # Wrint line to file
                
                # AFTER WRITE
                current_msg += 1
                # CHECK IF USER CLICK STOP BUTTON
                if client.force_stop[guild] == True :
                    break
            channel_count += 1 # After finish save message in channel
            if client.force_stop[guild] == True :
                break 

    # END LOOP CHANNEL
    end_time = time.time()
    if client.overtime[guild] == False:
        if client.force_stop[guild] == False :
            await interaction.edit_original_response(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=None)
        elif client.force_stop[guild] == True:
            await interaction.edit_original_response(content=f"**🛑 การดึงข้อความถูกยกเลิก**",view=None)
    elif client.overtime[guild] == True and client.force_stop[guild] == False:
        await channel.send(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=None)


# AI COMMAND
@client.tree.command(name='ai', description="🧠 เปิด/ปิดการคุยกับบอท")
@app_commands.choices(mode=[
    app_commands.Choice(name="Speak (Voice chat is not yet supported)",value="speak"),
    app_commands.Choice(name="Chat",value="chat"),
    app_commands.Choice(name="Turn Off ❌",value="off"),])

@app_commands.describe(mode="เลือกโหมดที่ต้องการ", language="เลือกภาษาที่ต้องการให้พูด (Only neural voices is supported)")
async def ai(interaction: discord.Interaction, mode: discord.app_commands.Choice[str], language: Optional[str]):
    await InfomationLog.sendlog(self=InfomationLog(interaction, mode.name)) # ขี้เกียจเก็บภาษา
    guild = interaction.guild_id
    if guild not in client.talk_to_ai:
        client.talk_to_ai[guild] = 0
        client.ai_active_channel[guild] = 0
    
    if mode.value == 'chat':
        # Disconnect voice
        if client.talk_to_ai[guild] == 2:
            voice_client = interaction.guild.voice_client
            try:
                await voice_client.disconnect()
            except:
                print("Error to disconnect voice")

        # Start chat
        if client.talk_to_ai[guild] != 1:
            client.talk_to_ai[guild] = 1
            client.ai_active_channel[guild] = interaction.channel_id
            client.chat_history[guild] = client.first_yuuka_prompt # Clear chat history
            await interaction.response.send_message(f"**✅ พร้อมคุยใน <#{interaction.channel_id}> แล้ว**")
        elif client.talk_to_ai[guild] == 1:
            await interaction.response.send_message(f"**ℹ️ บอทกำลังคุยอยู่ใน <#{client.ai_active_channel[guild]}>**")

    elif mode.value == 'speak':
        if client.talk_to_ai[guild] != 2:
            try:
                voice_channel = interaction.user.voice.channel
                voice = discord.utils.get(client.voice_clients, guild=interaction.guild)
                client.talk_to_ai[guild] = 2
                client.ai_active_channel[guild] = interaction.channel_id
                if language != None and tts_language_check.check(language):
                    client.voice_language[guild] = language
                    await interaction.response.send_message(f"**✅ พร้อมพูดใน <#{voice_channel.id}> ด้วยเสียง `{language}` แล้ว**")
                else:
                    client.voice_language[guild] = ""
                    await interaction.response.send_message(f"**✅ พร้อมพูดใน <#{voice_channel.id}> แล้ว**")

                client.chat_history[guild] = client.first_yuuka_prompt # Clear chat history
                
                if voice and voice.is_connected():
                    await voice.move_to(voice_channel)
                else:
                    voice = await voice_channel.connect()
                client.voice[guild] = voice
            
            except:
                await interaction.response.send_message("**จะให้พูดกับใคร U_U**")
                return
        elif client.talk_to_ai[guild] == 2:
            voice_channel = interaction.user.voice.channel
            await interaction.response.send_message(f"**ℹ️ บอทกำลังคุยอยู่ใน <#{voice_channel.id}>**")

    elif mode.value == 'off':
        if client.talk_to_ai[guild] == 2:
            voice_client = interaction.guild.voice_client
            try:
                await voice_client.disconnect()
            except:
                print("Error to disconnect voice")
        client.talk_to_ai[guild] = 0
        client.ai_active_channel[guild] = 0
        await interaction.response.send_message("**❌ ปิดการใช้งาน AI แล้ว**")


# Context Menu
@client.tree.context_menu(name='Search by Image')
async def searchbyimage(interaction: discord.Interaction, message: discord.Message):
    # Only for last image (Fix later)
    #try:
    await InfomationLog.contextlog(self=InfomationLog(interaction,message))
    guild = interaction.guild.id
    filePath = f"temp/autosave/{client.last_image[guild]}"
    searchUrl = 'https://yandex.com/images/search'
    files = {'upfile': ('blob', open(filePath, 'rb'), 'image/jpeg')}
    params = {'rpt': 'imageview', 'format': 'json', 'request': '{"blocks":[{"block":"b-page_type_search-by-image__link"}]}'}
    response = requests.post(searchUrl, params=params, files=files)
    query_string = json.loads(response.content)['blocks'][0]['params']['url']
    img_search_url= searchUrl + '?' + query_string

    search = discord.Embed(title = "**🔎 ค้นหาภาพคล้าย**", color = 0x5be259)
    search.set_thumbnail(url=client.last_image_url[guild])
    search.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    search.timestamp = interaction.created_at

    url_view = discord.ui.View()
    url_view.add_item(discord.ui.Button(label='ผลการค้นหา',emoji="🔎",style=discord.ButtonStyle.url, url=img_search_url))

    await interaction.response.send_message(embed=search, view=url_view)
    #except:
    #    await interaction.response.send_message("**❌ ไฟล์หมดอายุแล้ว**")


# Auto Command
@client.event
async def on_message(message):
    guild = message.guild.id
    # Auto Save Attachments with name
    try:
        extension = ""
        url = ""

        attachment_url = message.attachments[0]
        url = str(attachment_url.url)
        splitedbydot = url.split(".")
        splitedbyslash = splitedbydot[len(splitedbydot)-2].split("/")
        name = splitedbyslash[len(splitedbyslash)-1]
        extension = splitedbydot[len(splitedbydot)-1]

        FileName = name+"."+extension
        client.name_only[guild] = name
        r = requests.get(url, stream=True)
        with open(FileName, 'wb') as out_file:
            shutil.copyfileobj(r.raw, out_file)
        shutil.move(FileName, f"temp/autosave/{FileName}")
        print('Saving : ' + FileName)
        
        if extension == "png" or extension == "jpg" or extension == "jpeg" or extension == "webp":
            client.last_image[guild] = FileName
            client.last_image_url[guild] = url
            print(f"Saved {FileName} to Last Image ({guild})")
        elif extension == "mp4" or extension == "webm" or extension == "mkv" or extension == "avi" or extension == "mov" or extension == "flv" or extension == "wmv" or extension == "mpg" or extension == "mpeg":
            client.last_video[guild] = FileName
            client.last_video_url[guild] = url
            print(f"Saved {FileName} to Last Video ({guild})")
        elif extension == "mp3" or extension == "wav" or extension == "m4a" or extension == "flac" or extension == "ogg":
            client.last_audio[guild] = FileName
            client.last_audio_url[guild] = url
            print(f"Saved {FileName} to Last Audio ({guild})")
        elif extension == "pdf":
            client.last_pdf[guild] = FileName
            client.last_pdf_url[guild] = url
            print(f"Saved {FileName} to Last PDF ({guild})")
    except:
        pass

    # Check if guild is in the talk_to_ai dictionary, and add it if not
    if guild not in client.talk_to_ai:
        client.talk_to_ai[guild] = 0
        client.ai_active_channel[guild] = 0
        client.chat_history[guild] = client.first_yuuka_prompt
        client.voice[guild] = None
        client.voice_language[guild] = ""

    # Talk to AI
    if message.author.id != client.user.id and message.channel.id == client.ai_active_channel[guild]:
        if client.talk_to_ai[guild] == 1: # Chat
            async with message.channel.typing():
                response, client.chat_history[guild], log = chatgpt.generate_response(message.content, client.chat_history[guild], message.author.display_name)
                await InfomationLog.openailog(self=InfomationLog(None, log, message))
                await message.channel.send(response.replace("Yuuka: ", ""))
        elif client.talk_to_ai[guild] == 2: # Speak
            voice = client.voice[guild]
            response, client.chat_history[guild],log = chatgpt.generate_response(message.content, client.chat_history[guild], message.author.display_name)
            await InfomationLog.openailog(self=InfomationLog(None, log, message))
            speech_synthesis.tts(response.replace("Yuuka: ", ""), client.voice_language[guild], client.ai_active_channel[guild])
            voice.play(discord.FFmpegPCMAudio(f"temp/{client.ai_active_channel[guild]}_output.wav"))

@client.event
async def on_error(interaction, error):
    channel = client.get_channel(1003719893260185750)
    error_log = discord.Embed(title=f"⚠️ **Error**", color=0xff0000)
    error_log.add_field(name="ข้อผิดพลาด",value=f"```{error}```")
    await channel.send(embed=error_log)
    raise error
    # Why it does work?
    
@tasks.loop(seconds=30)
async def host_status_change():
    # Check Heroku Status
    if client.IsAnnouncement == False:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()[2]
        await client.change_presence(activity=discord.Game(name=f"CPU {cpu}% RAM {ram}%"))


@tasks.loop(minutes=10)
async def autodelete():
    # Delete autosave every 10 minutes
    dir = 'temp/autosave' # temp/test/autosave
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))

Token = os.environ['YuukaToken']
client.run(Token)