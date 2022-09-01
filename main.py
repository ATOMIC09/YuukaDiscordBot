import discord
from discord import app_commands, ui
from discord.ext import tasks
import os
import asyncio 
from utils import countdown_fn, youtubedl_fn, sectobigger, shorten_url
import requests
import shutil
import json
import psutil

MY_GUILD = discord.Object(id=720687175611580426) #CPRE 981567258222555186 # TESTER 720687175611580426

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
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)

intents = discord.Intents.all()
intents.members = True
client = MyClient(intents=intents)

class SendLog():
    def __init__(self, interaction, arg):
        self.interaction = interaction
        if arg == "nodata":
            self.arg = ""
        else:
            self.arg = arg

    async def send(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิรฟ์เวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
        log.add_field(name="ช่อง",value=f"`{self.interaction.channel}` ({self.interaction.channel_id})")
        log.add_field(name="ผู้เขียน",value=f"`{self.interaction.user}` ({self.interaction.user.id})")
        log.add_field(name="คำสั่ง",value=f"```/{self.interaction.command.name} {self.arg}```")

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{self.interaction.guild_id}/{self.interaction.channel_id}/{self.interaction.id}"))
        
        await channel.send(embed=log,view=url_view)
    
    async def context(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x455EE8)
        log.set_author(name=self.interaction.user, icon_url=self.interaction.user.display_avatar.url)
        log.timestamp = self.interaction.created_at
        log.add_field(name="เซิรฟ์เวอร์",value=f"`{self.interaction.guild}` ({self.interaction.guild_id})")
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
    
    await SendLog.send(self=SendLog(interaction,"nodata"))
    # หน้าเมนู Embed
    util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
    util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=False)
    util.add_field(name="**⛔ ยกเว้นคำสั่ง Countdis**", value="`/except`", inline=False)
    util.add_field(name="**📨 ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=False)
    util.add_field(name="**🎬 ขอไฟล์จาก Youtube**", value="`/youtube`", inline=False)
    util.add_field(name="**📨 ส่งข้อความ**", value="`/send`", inline=False)
    util.add_field(name="**🦵 เตะคนออกจากแชทเสียง**", value="`/kick`", inline=False)

    update = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *📌 ประวัติการอัพเดท*", color=0xdcfa80)
    update.add_field(name="1️⃣ V 1.0 | 29/07/2022", value="• Add: Countdis\n• Add: Feedback")
    update.add_field(name="1️⃣ V 1.1 | 02/08/2022", value="• Add: Log\n• Add: Youtube\n• Add: Search by Image\n• Add: AutoDelete Temp\n• Add: Hosting Status\n• Improve: Embed Feedback")
    update.add_field(name="1️⃣ V 1.2 | 02/09/2022", value="• Add: Send command\n• Add: Kick member from voice chat")

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
    await SendLog.send(self=SendLog(interaction,"nodata"))
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


################################################# Youtube #################################################
@client.tree.command(name="youtube",description="🎬 ขอไฟล์จาก Youtube")
@app_commands.describe(url="ใส่ URL ของคลิปใน Youtube")
async def youtube_def(interaction: discord.Interaction, url: str):
    await SendLog.send(self=SendLog(interaction,url))
    await interaction.response.send_message(f"🔎 **กำลังหา** `{url}`")

    # เก็บข้อมูลดิบ
    title = youtubedl_fn.yt_title(url)
    ext = youtubedl_fn.yt_ext(url)
    upload_date = youtubedl_fn.yt_upload_date(url)
    channel = youtubedl_fn.yt_channel(url)
    duration = youtubedl_fn.yt_duration(url)
    view_count = youtubedl_fn.yt_view_count(url)
    like_count = youtubedl_fn.yt_like_count(url)
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
    dl.add_field(name="🥼 ช่อง", value=f"`{channel}`", inline=False)
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

    await interaction.edit_original_message(content="",embed=dl,view=url_view)


################################################# Send Message #################################################
@client.tree.command(description="📨 ส่งข้อความด้วยบอท")
@app_commands.describe(channel="ช่องข้อความที่จะส่ง",message="ข้อความ")
async def send(interaction: discord.Interaction, channel: discord.TextChannel, *, message: str):
    combine_arg = str(channel.id) + " " + message
    await SendLog.send(self=SendLog(interaction,combine_arg))
    await interaction.response.send_message(content=f'"{message}" ถูกส่งไปยัง {channel.mention}',ephemeral=True)
    await channel.send(message)


################################################# Kick member from vc #################################################
@client.tree.command(description="🦵 เตะสมาชิกจากช่องเสียง")
@app_commands.describe(member="ผู้ใช้")
async def kick(interaction: discord.Interaction, member: discord.Member):
    await member.move_to(None)
    await SendLog.send(self=SendLog(interaction,str(member.id)))
    await interaction.response.send_message(content=f'<@{member.id}> ถูกเตะออกจาก `{member.voice.channel}`',ephemeral=True)
    await interaction.send(member)


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
    await SendLog.send(self=SendLog(interaction,"nodata"))
    await interaction.response.send_modal(FeedbackModal())

################################################# Context Command #################################################
@client.tree.context_menu(name='Search by Image')
async def searchbyimage(interaction: discord.Interaction, message: discord.Message):
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
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory()[2]
    await client.change_presence(activity=discord.Game(name=f"CPU {cpu}% RAM {ram}%"))

@tasks.loop(minutes=30)
async def autodelete():
    # Delete autosave
    dir = 'temp/autosave' # temp/test/autosave
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))

Token = os.environ['YuukaTesterToken']
client.run(Token)