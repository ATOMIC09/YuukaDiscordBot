import discord
from discord import app_commands, ui
from discord.ext import tasks
import os
import asyncio 
from utils import countdown_fn, youtubedl_fn, sectobigger, shorten_url, imageprocess_fn, filesize, ai_core
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

#MY_GUILD = discord.Object(id=720687175611580426) #CPRE 981567258222555186 # TESTER 720687175611580426

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    
    async def on_ready(self):
        if not host_status_change.is_running():
            host_status_change.start()
        if not autodelete.is_running():
            autodelete.start()
            
        await client.change_presence(activity=discord.Game(name="💤 Standby..."))
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------------------------------------------------')
    
    async def setup_hook(self):
        await self.tree.sync()
    

intents = discord.Intents.all()
intents.members = True
client = MyClient(intents=intents)
client.IsAnnouncement = False

class SendLog():
    def __init__(self, interaction, arg="nodata", arg2="nodata"):
        self.interaction = interaction
        if arg == "nodata":
            self.arg = ""
        else:
            self.arg = arg

        if arg2 == "nodata":
            self.arg2 = ""
        else:
            self.arg2 = arg2

    async def send(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิร์ฟเวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="หมวดหมู่",value=f"`{self.interaction.channel.category.name}` ({self.interaction.channel.category.id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```/{self.interaction.command.name} {self.arg} {self.arg2}```")

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        
        await channel.send(embed=log,view=url_view)
    
    async def context(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิร์ฟเวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="หมวดหมู่",value=f"`{self.interaction.channel.category.name}` ({self.interaction.channel.category.id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```{self.interaction.command.name} กับรูปภาพ```")
        log.set_image(url=self.arg.attachments[0])

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        
        await channel.send(embed=log,view=url_view)


################################################# Help #################################################
@client.tree.command(description="❔ ความช่วยเหลือ")
async def help(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction))
    # หน้าเมนู Embed
    util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
    util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=False)
    util.add_field(name="**⛔ ยกเว้นคำสั่ง Countdis**", value="`/except`", inline=False)
    util.add_field(name="**🛑 ยกเลิกการนับถอยหลัง**", value="`/cancel`", inline=False)
    util.add_field(name="**📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=False)
    util.add_field(name="**🎬 ขอไฟล์จาก Youtube**", value="`/youtube`", inline=False)
    util.add_field(name="**📨 ส่งข้อความ**", value="`/send`", inline=False)
    util.add_field(name="**🦵 เตะคนออกจากแชทเสียง**", value="`/kick`", inline=False)
    util.add_field(name="**🍟 ทอดกรอบภาพ**", value="`/deepfry`", inline=False)
    util.add_field(name="**📢 สแปมคนไม่มา**", value="`/spam`", inline=False) 
    util.add_field(name="**📝 เช็คชื่อในช่องเสียง**", value="`/attendance`", inline=False)
    util.add_field(name="**🔎 เช็คคนขาดประชุม**", value="`/absent`", inline=False)

    ai = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🤖 Artificial Intelligence*", color=0x03dffc)
    ai.add_field(name="**🧠 คุยกับบอท**", value="`/ai`", inline=False)
    ai.add_field(name="**🎒 รวมคำสั่งเกี่ยวกับการเทรน ตรวจสอบ และลบฐานข้อมูล**", value="`/train`", inline=False)
    ai.add_field(name="**🗞️ บันทึกประวัติการส่งข้อความ**", value="`/getchat`", inline=False)

    update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัพเดท*", color=0xdcfa80)
    update.add_field(name="1️⃣ V 1.0 | 29/07/2022", value="• Add: Countdis\n• Add: Feedback")
    update.add_field(name="2️⃣ V 1.1 | 02/08/2022", value="• Add: Log\n• Add: Youtube\n• Add: Search by Image\n• Add: AutoDelete Temp\n• Add: Hosting Status\n• Improve: Embed Feedback")
    update.add_field(name="3️⃣ V 1.2 | 02/09/2022", value="• Add: Send command\n• Add: Kick member from voice chat")
    update.add_field(name="4️⃣ V 1.3 | 02/10/2022", value="• Add: Deepfry command\n• Improve: Change Guild to Global Command")
    update.add_field(name="5️⃣ V 1.4 | 11/10/2022", value="• Add: Spam Mentions")
    update.add_field(name="6️⃣ V 1.5 | 24/10/2022", value="• Add: Announcement(For Dev Only)\n• Add: Attendance\n• Add: Absent\n• Add: Cancel\n• Hotfix: Spam Mentions")
    update.add_field(name="7️⃣ V 1.6 | 14/12/2022", value="• Add: AI\n• Change: Emoji and Decoration")


    select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
    discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
    discord.SelectOption(label="Artificial Intelligence",emoji="🤖",description="คำสั่งเกี่ยวกับ AI ของบอท",value="ai",default=False),
    discord.SelectOption(label="ประวัติการอัพเดท",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
    ])

    async def my_callback(interaction):
        if select.values[0] == "util":
            await interaction.response.edit_message(embed=util)

        elif select.values[0] == "update":
            await interaction.response.edit_message(embed=update)

        elif select.values[0] == "ai":
            await interaction.response.edit_message(embed=ai)

    select.callback = my_callback
    view = discord.ui.View()
    view.add_item(select)

    await interaction.response.send_message(embed=util, view=view)


################################################# Countdis #################################################
client.timestop = 0
client.member_except = []
client.last_use = [0]

@client.tree.command(description="⏱️ นับถอยหลังและตัดการเชื่อมต่อ")
@app_commands.describe(time="ใส่เวลาเป็นหน่วยวินาที")
async def countdis(interaction: discord.Interaction, time: str):
    try:
        members = interaction.user.voice.channel.members
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
                await interaction.edit_original_response(content=output)
                await asyncio.sleep(1)
                time_int -= 1

                if client.timestop == -22052603:
                    await interaction.edit_original_response(content="**การนับถอยหลังถูกยกเลิก 🛑**")
                    break
            if client.timestop != -22052603:
                channel = interaction.user.voice.channel
            
                await interaction.edit_original_response(content="**หมดเวลา 🔔**")
                
                if client.member_except == []: # ไม่มีใครยกเว้น
                    for member in members:
                        await member.move_to(None)
                        people_counter += 1

                    client.member_except = []
                    client.last_use = [0]
                    await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อจำนวน {people_counter} คน จาก `{channel}` สำเร็จแล้ว**")

                else:
                    for member in members:
                        if member not in client.member_except: # เช็คว่าใครไม่ออก
                            await member.move_to(None)
                            people_counter += 1

                    client.member_except = []
                    client.last_use = [0]
                    await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อจำนวน {people_counter} คน จาก `{channel}` สำเร็จแล้ว**")
                    
    except:
        await interaction.response.send_message(content="**ไม่เข้าห้องเสียงแล้วจะให้ถีบยังไงอะ (●'◡'●)**")


################################################# Except #################################################
@client.tree.command(name="except",description="⛔ ยกเว้นคำสั่ง Countdis")
async def except_def(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction))
    user = interaction.user
    if user.id not in client.last_use:
        client.member_except.append(user) # คนที่จะไม่ออก
        client.last_use.pop(0)
        client.last_use.append(user.id)
        await interaction.response.send_message(content=f"**<@{user.id}> ได้รับการยกเว้น <:Approve:921703512382009354>**")
    else:
        client.member_except.remove(user) # คนที่จะออก
        client.last_use.pop(0)
        client.last_use.append(0)
        await interaction.response.send_message(content=f"**<@{user.id}> ถูกลบออกจากรายการที่ยกเว้น <:Deny:921703523111022642>**")


################################################# Cancel #################################################
@client.tree.command(name="cancel",description="❌ ยกเลิกการนับถอยหลัง")
async def cancel(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction))
    client.timestop = -22052603
    await interaction.response.send_message(content="**✅ ยกเลิกการนับถอยหลังแล้ว**")


################################################# Youtube #################################################
@client.tree.command(name="youtube",description="🎬 ขอไฟล์จาก Youtube")
@app_commands.describe(url="ใส่ URL ของคลิปใน Youtube")
async def youtube_def(interaction: discord.Interaction, url: str):
    await SendLog.send(self=SendLog(interaction,url))
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


################################################# Send Message #################################################
@client.tree.command(description="📨 ส่งข้อความด้วยบอท")
@app_commands.describe(channel="ช่องข้อความที่จะส่ง",message="ข้อความ")
async def send(interaction: discord.Interaction, channel: discord.TextChannel, *, message: str):
    combine_arg = str(channel.id) + " " + message
    await SendLog.send(self=SendLog(interaction,combine_arg))
    await interaction.response.send_message(f'"{message}" ถูกส่งไปยัง {channel.mention}',ephemeral=True)
    await channel.send(message)


################################################# Kick member from VC #################################################
@client.tree.command(description="🦵 เตะสมาชิกจากช่องเสียง")
@app_commands.describe(member="ผู้ใช้")
async def kick(interaction: discord.Interaction, member: discord.Member):
    await SendLog.send(self=SendLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    await interaction.response.send_message(f'<@{member.id}> ถูกเตะออกจาก `{member.voice.channel}`',ephemeral=True)
    await member.move_to(None)


################################################# Feedback #################################################
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
    await SendLog.send(self=SendLog(interaction))
    await interaction.response.send_modal(FeedbackModal())

################################################### Deepfry ###################################################
@client.tree.command(description="🍟 ทอดกรอบภาพ")
async def deepfry(interaction: discord.Interaction):
    try:
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        shutil.copy(f"temp/autosave/{client.last_image}", f"asset/deepfry/deepfryer_input/{client.last_image}")
        imageprocess_fn.deepfry(f"asset/deepfry/deepfryer_input/{client.last_image}")
        await SendLog.send(self=SendLog(interaction))

        if "_deepfryer" in client.name_only:
            path = f'asset/deepfry/deepfryer_output/{client.name_only}.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        else:
            path = f'asset/deepfry/deepfryer_output/{client.name_only}_deepfryer.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
    except:
        await interaction.edit_original_response(content="❌ **ไม่พบรูปภาพ**")


################################################# Spam Mentions #################################################
@client.tree.command(description="📢 สแปมคนไม่มา")
@app_commands.describe(member="ผู้ใช้", message="ข้อความ", delay="การหน่วงเวลา", amount="จำนวนครั้ง")
async def spam(interaction: discord.Interaction, member: discord.Member, *, message: str, delay: int = 2, amount: int = 5):
    await SendLog.send(self=SendLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    client.stopSpam = False

    stop = discord.ui.Button(label="หยุดสแปม",emoji="⏹",style=discord.ButtonStyle.red)
    async def stop_callback(interaction):
        client.stopSpam = True

    stop.callback = stop_callback
    view = discord.ui.View()
    view.add_item(stop)
    await interaction.response.send_message(content=f'<a:LoadingGIF:1052561472263299133> **กำลังสแปม** {message} **กับ** <@{member.id}>',ephemeral=True,view=view)
    
    for i in range(amount):
        if client.stopSpam == False:
            await asyncio.sleep(delay)
            await interaction.followup.send(f'{message} <@{member.id}>')
        else:
            break
    if client.stopSpam == False:
        await interaction.edit_original_response(content=f'✅ **สแปม** {message} **กับ** <@{member.id}> **จบแล้ว**',view=None)    
    else:
        await interaction.edit_original_response(content=f'⛔ **หยุดสแปม** {message} **กับ** <@{member.id}> **แล้ว**',view=None)


################################################# Announcement #################################################
@client.tree.command(description="📢 ประกาศ (เฉพาะผู้สร้าง)")
@app_commands.describe(message="ข้อความที่จะประกาศ")
async def announce(interaction: discord.Interaction, *, message: str):
    if interaction.user.id == 269000561255383040:
        if client.IsAnnouncement == False:
            await SendLog.send(self=SendLog(interaction, message))
            client.IsAnnouncement = True
            await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
            await interaction.response.send_message(f'✅ **ประกาศ** {message} **เรียบร้อย**',ephemeral=True)
        else:
            client.IsAnnouncement = False
            await interaction.response.send_message(f'⏹ **หยุดประกาศเรียบร้อย**',ephemeral=True)


################################################# Attendance #################################################
@client.tree.command(description="📝 บันทึกการเข้าประชุม")
async def attendance(interaction: discord.Interaction):
    try:
        vc = interaction.user.voice.channel
        member = ""
        count = 0

        for user in vc.members:
            if user.bot == False:
                member += f'> {user.display_name}\n'
                count += 1

        await SendLog.send(self=SendLog(interaction))
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
        await interaction.response.send_message(f"**ต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้ ┐⁠(⁠ ⁠˘⁠_⁠˘⁠)⁠┌**")


################################################# Absent #################################################
@client.tree.command(description="🔎 หาผู้ขาดการประชุม")
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
            await SendLog.send(self=SendLog(interaction))
        else:
            await SendLog.send(self=SendLog(interaction,role))
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


################################################ Save Chat History ################################################
@client.tree.command(description="🗞️ บันทึกประวัติการส่งข้อความ")
async def getchat(interaction: discord.Interaction):
    await SendLog.send(self=SendLog(interaction))
    channel = interaction.channel
    start_time = time.time()
    client.force_stop = False
    client.overtime = False
    channel_count = 0
    channel_total = len(interaction.guild.text_channels)
    await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> 0% กำลังเริ่มต้น...ตรวจพบ {channel_total} ช่อง**")

    # LOOP CHANNEL
    for channel in interaction.guild.text_channels:
        percent_total = round((channel_count / channel_total) * 100, 1)

        stop_button = discord.ui.Button(label="หยุด",emoji="❎",style=discord.ButtonStyle.red)
        
        async def stop_callback(interaction):
            client.force_stop = True

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
                        client.overtime = True

                # WHILE WRITE
                    # f.write takes too much time for update progress in discord
                    # Means it will update every time a single line is written.
                f.write(f"{message.content}\n") # Wrint line to file

                # AFTER WRITE
                current_msg += 1

                # CHECK IF USER CLICK STOP BUTTON
                if client.force_stop == True :
                    break
            
            channel_count += 1 # After finish save message in channel
            
            if client.force_stop == True :
                break 

    # END LOOP CHANNEL
    end_time = time.time()
    if client.overtime == False:
        if client.force_stop == False :
            await interaction.edit_original_response(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=None)
        elif client.force_stop == True:
            await interaction.edit_original_response(content=f"**🛑 การดึงข้อความถูกยกเลิก**",view=None)
    elif client.overtime == True and client.force_stop == False:
        await channel.send(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=None)


################################################# AI #################################################
@client.tree.command(description="🎒 รวมคำสั่งเกี่ยวกับการเทรน ตรวจสอบ และลบฐานข้อมูล")
@app_commands.choices(mode=[
    app_commands.Choice(name="🌍 Train with English Corpus",value="english"),
    app_commands.Choice(name="🌾 Train with Thai Corpus",value="thai"),
    app_commands.Choice(name="🗞️ Train with Chat history",value="chat"),
    app_commands.Choice(name="📏 Check size of the chat in Database",value="checkchat"),
    app_commands.Choice(name="📐 Check AI database size",value="checkdb"),
    app_commands.Choice(name="🧹 Delete chat history in database",value="delchat"),
    app_commands.Choice(name="❌ Delete AI database",value="deldb")
    ])

@app_commands.describe(mode="เลือกโหมดที่ต้องการ")
async def train(interaction: discord.Interaction, mode: discord.app_commands.Choice[str]):
    await SendLog.send(self=SendLog(interaction,mode.name))
    await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> กำลังทำงาน**")
    if mode.value == "english":
        ai_core.train_english() 
        await interaction.edit_original_response(content=f"**✅ เทรนบอทเสร็จสิ้น `({filesize.getsize('db.sqlite3')})`**")
    
    elif mode.value == "thai":
        ai_core.train_thai()
        await interaction.edit_original_response(content=f"**✅ เทรนบอทเสร็จสิ้น `({filesize.getsize('db.sqlite3')})`**")
    
    elif mode.value == "chat":
        contents = os.listdir("asset/chat")
        if contents:
            ai_core.train_from_chat()
            await interaction.edit_original_response(content=f"**✅ เทรนบอทเสร็จสิ้น `({filesize.getsize('db.sqlite3')})`**")
        else:
            await interaction.edit_original_response(content=f"**❌ ยังไม่พบการดึงข้อมูลแชท ลองใช้ `/getchat`**")
    
    elif mode.value == "checkchat":
        try:
            await interaction.edit_original_response(content=f"**📏 ขนาดข้อมูลแชทใน Database `{filesize.getfoldersize(f'asset/chat')}`**")
        except:
            await interaction.edit_original_response(content=f"**❌ ยังไม่พบการดึงข้อมูลแชท ลองใช้ `/getchat`**")

    elif mode.value == "checkdb":
        try:
            await interaction.edit_original_response(content=f"**📐 ขนาดข้อมูล AI database `{filesize.getsize('db.sqlite3')}`**")
        except:
            await interaction.edit_original_response(content=f"**❌ ไม่พบ AI database ลองเทรนบอทก่อน**")

    elif mode.value == "delchat":
        try:
            ai_core.delete_chat()
            await interaction.edit_original_response(content=f"**✅ ลบข้อมูลแชทใน Database เสร็จสิ้น**")
        except:
            await interaction.edit_original_response(content=f"**❌ ไม่พบข้อมูลแชทใน Database**")

    elif mode.value == "deldb":
        try:
            ai_core.delete_db()
            await interaction.edit_original_response(content=f"**✅ ลบ Database เสร็จสิ้น**")
        except:
            await interaction.edit_original_response(content=f"**❌ ไม่พบ AI database**")

@client.tree.command(description="🧠 คุยกับบอท")
@app_commands.describe(message="ข้อความ")
async def ai(interaction: discord.Interaction, message: str):
    await SendLog.send(self=SendLog(interaction,message))
    if os.path.exists("db.sqlite3"):
        await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> กำลังส่งข้อความไปหาบอท**")
        response = ai_core.get_response(message)
        await interaction.edit_original_response(content=response)
    else:
        await interaction.response.send_message(f"**❌ ยังไม่มี Database ลองใช้ `/train`**")


################################################# Context Command #################################################
@client.tree.context_menu(name='Search by Image')
async def searchbyimage(interaction: discord.Interaction, message: discord.Message):
    try:
        await SendLog.context(self=SendLog(interaction,message))
        filePath = f"temp/autosave/{client.last_image}"
        searchUrl = 'https://yandex.com/images/search'
        files = {'upfile': ('blob', open(filePath, 'rb'), 'image/jpeg')}
        params = {'rpt': 'imageview', 'format': 'json', 'request': '{"blocks":[{"block":"b-page_type_search-by-image__link"}]}'}
        response = requests.post(searchUrl, params=params, files=files)
        query_string = json.loads(response.content)['blocks'][0]['params']['url']
        img_search_url= searchUrl + '?' + query_string

        search = discord.Embed(title = "**🔎 ค้นหาภาพคล้าย**", color = 0x5be259)
        search.set_thumbnail(url=client.last_image_url)
        search.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        search.timestamp = interaction.created_at

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='ผลการค้นหา',emoji="🔎",style=discord.ButtonStyle.url, url=img_search_url))

        await interaction.response.send_message(embed=search, view=url_view)
    except:
        await interaction.response.send_message("**❌ ไฟล์หมดอายุแล้ว**")


################################################# Auto Save Attachment #################################################
@client.event
async def on_message(message):
    # Auto Save Attachments with name
    extension = ""
    url = ""

    try:
        attachment_url = message.attachments[0]
        url = str(attachment_url.url)
        splitedbydot = url.split(".")
        splitedbyslash = splitedbydot[len(splitedbydot)-2].split("/")
        name = splitedbyslash[len(splitedbyslash)-1]
        extension = splitedbydot[len(splitedbydot)-1]

        FileName = name+"."+extension
        client.name_only = name
        r = requests.get(url, stream=True)
        with open(FileName, 'wb') as out_file:
            shutil.copyfileobj(r.raw, out_file)
        shutil.move(FileName, f"temp/autosave/{FileName}")
        if client.IsAnnouncement == False:
            await client.change_presence(activity=discord.Game(name=f"💾 {FileName}"))
        print('Saving : ' + FileName)

        if extension == "png" or extension == "jpg" or extension == "jpeg" or extension == "webp":
            client.last_image = FileName
            client.last_image_url = url
            print(f"Saved {FileName} to Last Image")
        elif extension == "mp4" or extension == "webm" or extension == "mkv" or extension == "avi" or extension == "mov" or extension == "flv" or extension == "wmv" or extension == "mpg" or extension == "mpeg":
            client.last_video = FileName
            client.last_video_url = url
            print(f"Saved {FileName} to Last Video")
        elif extension == "mp3" or extension == "wav" or extension == "m4a" or extension == "flac" or extension == "ogg":
            client.last_audio = FileName
            client.last_audio_url = url
            print(f"Saved {FileName} to Last Audio")
        elif extension == "pdf":
            client.last_pdf = FileName
            client.last_pdf_url = url
            print(f"Saved {FileName} to Last PDF")
    
    except:
        print("No attachment")


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