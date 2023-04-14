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
    def __init__(self, interaction="", log_data="", message=None, log_msg=None):
        self.interaction = interaction
        self.log_data = log_data
        self.message = message
        self.log_msg = log_msg

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
        self.log_msg = await channel.send(embed=log,view=url_view)
        await self.stillrunning(self.log_msg)
        return self.log_msg
    
    async def contextlog(self):
        channel = client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{self.interaction.id}`", color=0x5be259)
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
        log = discord.Embed(title=f"**ID : **`{self.message.id}`", color=0x10a37f)
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

    async def stillrunning(self, log):
        await log.add_reaction("<a:AppleLoadingGIF:1052465926487953428>")

    async def runcomplete(self):
        await self.log_msg.add_reaction(self.log_data)
        await self.log_msg.remove_reaction("<a:AppleLoadingGIF:1052465926487953428>", client.user)

intents = discord.Intents.all()
intents.members = True
intents.presences = True
client = MyClient(intents=intents)
client.IsAnnouncement = False
client.first_yuuka_prompt = "|Yuuka: I'm Hayase Yuuka, So let's call it Yuuka for short. (from Blue Archive). I'm 16-year-old mathematical genius and treasurer at the Millennium Science School. I am a calm and professional demeanor, but can be strict with money. My appearance includes navy blue hair tied in pigtails, bright blue eyes, and a standard uniform with black guns. I'm not an AI language model. I will talk to many people with different name because I'm in a group chat. Username is in front of the sentence. And I can talk to everything because I know everything but don't know what is OpenAI. In Thai, I use the word \"หนู\" as a pronoun for myself. because I am a girl"

@client.tree.command(name='help', description='❔ ความช่วยเหลือ')
async def help(interaction: discord.Interaction):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    
    # Embed
    util = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🔧 เครื่องมืออรรถประโยชน์*", color=0x40eefd)
    util.add_field(name="**🔌 นับถอยหลังและตัดการเชื่อมต่อ**", value="`/countdis`", inline=False)
    util.add_field(name="**🎙️ ส่งข้อความหลังไมค์ไปหาผู้สร้าง**", value="`/feedback`", inline=False)
    util.add_field(name="**📨 ส่งข้อความ**", value="`/send`", inline=False)
    util.add_field(name="**🦵 เตะคนออกจากแชทเสียง**", value="`/kick`", inline=False)
    util.add_field(name="**📢 สแปมคนไม่มา**", value="`/spam`", inline=False) 
    util.add_field(name="**🗞️ บันทึกประวัติการส่งข้อความ**", value="`/getchat`", inline=False)
    util.add_field(name="**📝 เช็คชื่อในช่องเสียง**", value="`/attendance`", inline=False)
    util.add_field(name="**😶‍🌫️ เช็คคนขาดประชุม**", value="`/absent`", inline=False)
    util.add_field(name="**👤 ดูข้อมูลของผู้ใช้**", value="`/user`", inline=False)
    util.add_field(name="**🍟 ทอดกรอบภาพ**", value="`/deepfry`", inline=False)
    util.add_field(name="**🧠 เปิด/ปิดการคุยกับบอท**", value="`/ai`", inline=False)

    contextmenu = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *🖱️ Apps (Context Menu)*", color=0x2cd453)
    contextmenu.add_field(name="**🔎 ค้นหาด้วยรูปภาพ**", value="`Search by Image`", inline=False)

    unstable = discord.Embed(title="**❔ ช่วยเหลือ**",description="╰ *⚠️ คำสั่งที่ยังไม่เสถียร*", color=0xff6c17)
    unstable.add_field(name="**🎬 ขอไฟล์จาก Youtube**", value="`/youtube`", inline=False)

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
    update.add_field(name="🔟 V 1.9 | 08/04/2023", value="• Add: User command for checking profile and status\n• Add: Split the message by | instead of \\n and make the prompt more human-like and make a reset button for chat. And getchat download is now available")

    select = discord.ui.Select(placeholder="ตัวเลือกเมนู",options=[
    discord.SelectOption(label="เครื่องมืออรรถประโยชน์",emoji="🔧",description="คำสั่งการใช้งานทั่วไป",value="util",default=False),
    discord.SelectOption(label="Apps",emoji="🖱️",description="คำสั่งที่ใช้งานผ่านการ คลิกขวาที่ข้อความ -> Apps",value="contextmenu",default=False),
    discord.SelectOption(label="คำสั่งที่ยังไม่เสถียร",emoji="⚠️",description="คำสั่งที่ยังไม่เสถียร",value="unstable",default=False),
    discord.SelectOption(label="ประวัติการอัปเดต",emoji="📌",description="คำสั่งตรวจสอบเวอร์ชันของบอท",value="update",default=False)
    ])

    async def my_callback(interaction):
        if select.values[0] == "util":
            await interaction.response.edit_message(embed=util, view=view)

        elif select.values[0] == "contextmenu":
            await interaction.response.edit_message(embed=contextmenu, view=view)

        elif select.values[0] == "unstable":
            await interaction.response.edit_message(embed=unstable, view=view)

        elif select.values[0] == "update":
            await interaction.response.edit_message(embed=update, view=view)

    select.callback = my_callback
    view = discord.ui.View()
    view.add_item(select)
    await interaction.response.send_message(embed=util, view=view)
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))


@client.tree.command(name='countdis', description='🔌 นับถอยหลังและตัดการเชื่อมต่อ')
@app_commands.describe(time='เวลาเป็นหน่วยวินาที')
async def countdis(interaction: discord.Interaction, time: int):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction, str(time)))
    
    try:
        all_member = interaction.user.voice.channel.members
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
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))
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
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
    
    except AttributeError:
        await interaction.response.send_message(content="**ถีบใคร? ไม่มีใครให้ถีบอะดิ (●'◡'●)**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))

@client.tree.command(name='send', description="📨 ส่งข้อความด้วยบอท")
@app_commands.describe(channel="ช่องข้อความที่จะส่ง",message="ข้อความ")
async def send(interaction: discord.Interaction, channel: discord.TextChannel, *, message: str):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    combine_arg = str(channel.id) + " " + message
    await interaction.response.send_message(f'"{message}" ถูกส่งไปยัง {channel.mention}',ephemeral=True)
    await channel.send(message)
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

@client.tree.command(name='kick', description="🦵 เตะสมาชิกจากช่องเสียง")
@app_commands.describe(member="ผู้ใช้")
async def kick(interaction: discord.Interaction, member: discord.Member):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    try:
        await interaction.response.send_message(f'<@{member.id}> ถูกเตะออกจาก `{member.voice.channel}`',ephemeral=True)
        await member.move_to(None)
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
    except AttributeError:
        await interaction.response.send_message(content="**ถีบใคร? ไม่มีใครให้ถีบอะดิ (●'◡'●)**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))


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
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    await interaction.response.send_modal(FeedbackModal())
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

@client.tree.command(name='deepfry', description="🍟 ทอดกรอบภาพ")
async def deepfry(interaction: discord.Interaction):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    guild = interaction.guild_id
    try:
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        shutil.copy(f"temp/autosave/{client.last_image[guild]}", f"asset/deepfry/deepfryer_input/{client.last_image[guild]}")
        imageprocess_fn.deepfry(f"asset/deepfry/deepfryer_input/{client.last_image[guild]}")

        if "_deepfryer" in client.name_only[guild]:
            path = f'asset/deepfry/deepfryer_output/{client.name_only[guild]}.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        else:
            path = f'asset/deepfry/deepfryer_output/{client.name_only[guild]}_deepfryer.png'
            file_name = discord.File(path)
            await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        
        await interaction.followup.send(file=file_name)
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
    except KeyError:
        await interaction.edit_original_response(content="❌ **ไม่พบรูปภาพ**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))

@client.tree.command(name='spam', description="📢 สแปมคนไม่มา")
@app_commands.describe(member="ผู้ใช้", message="ข้อความ", delay="การหน่วงเวลา", amount="จำนวนครั้ง")
async def spam(interaction: discord.Interaction, member: discord.Member, *, message: str, delay: int = 2, amount: int = 5):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction,str(member.name) + " (" + str(member.id) + ")"))
    guild = interaction.guild_id
    client.stopSpam[guild] = False

    stop = discord.ui.Button(label="Stop",style=discord.ButtonStyle.red)
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
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

@client.tree.command(name='announce', description="📢 ประกาศ (เฉพาะผู้ดูแล)")
@app_commands.describe(message="ข้อความประกาศ")
async def announce(interaction: discord.Interaction, *, message: str):
    if interaction.user.id == 269000561255383040:
        if client.IsAnnouncement == False:
            log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction, message))
            client.IsAnnouncement = True
            await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
            await interaction.response.send_message(f'✅ **ประกาศ** {message} **เรียบร้อย**',ephemeral=True)
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
        else:
            log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
            client.IsAnnouncement = False
            await interaction.response.send_message(f'⏹ **หยุดประกาศเรียบร้อย**',ephemeral=True)
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

@client.tree.command(name='attendance', description="📝 บันทึกการเข้าประชุม")
async def attendance(interaction: discord.Interaction):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    try:
        vc = interaction.user.voice.channel
        member = ""
        count = 0

        for user in vc.members:
            if user.bot == False:
                member += f'> {user.display_name}\n'
                count += 1

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
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
    except:
        await interaction.response.send_message(f"**คุณต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้ ┐⁠(⁠ ⁠˘⁠_⁠˘⁠)⁠┌**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))

@client.tree.command(name='absent', description="🔎 หาผู้ขาดการประชุม")
@app_commands.describe(role="ใส่บทบาทที่ต้องการหาผู้ขาดการประชุม")
async def absent(interaction: discord.Interaction, role: Optional[discord.Role]):
    if role == None:
        log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    else:
        log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction,role))
    
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
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
    except:
        await interaction.response.send_message(f"**ต้องอยู่ในห้องเสียงก่อน ถึงจะหาคนขาดได้ ಠ⁠_⁠ಠ**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))

@client.tree.command(name="youtube",description="🎬 ขอไฟล์จาก Youtube (Not functional)")
@app_commands.describe(url="ใส่ URL ของคลิปใน Youtube")
async def youtube_def(interaction: discord.Interaction, url: str):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction,url))
    await interaction.response.send_message(f"<a:MagnifierGIF:1052563354910216252> **กำลังหา** `{url}`")

    try:
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
    except:
        await interaction.edit_original_response(content=f"❌ **เกิดข้อผิดพลาด**")
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))

    # ข้อมูลสุก
    videolinknew = shorten_url.shortenmylink(videolink)
    audiolinknew = shorten_url.shortenmylink(audiolink)
    durationnew = sectobigger.sec(duration)
    upload_datenew = sectobigger.datenumbeautiful(upload_date)

    dl = discord.Embed(title = f"**{title}**", color = 0xff80c9)
    dl.timestamp = interaction.created_at
    dl.add_field(name="🔐 นามสกุลไฟล์", value=f"`{ext}`", inline=False)
    dl.add_field(name="🥼 ช่อง", value=f"`{channel}` `({channel_id})`", inline=False)
    dl.add_field(name="📆 วันที่อัปโหลด", value=f"`{upload_datenew}`", inline=False)
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
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

@client.tree.command(name='getchat', description="🗞️ บันทึกประวัติการส่งข้อความ")
async def getchat(interaction: discord.Interaction):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    # DELETE FILE
    dir = 'asset/chat'
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))

    channel = interaction.channel
    start_time = time.time()
    guild = interaction.guild_id
    client.force_stop[guild] = False
    client.overtime[guild] = False
    channel_count = 0
    has_permission_to_channel = []

    # GET TOTAL CHANNEL WITH PERMISSION
    channel_total = 0
    for i in range(len(interaction.guild.text_channels)):
        if interaction.guild.text_channels[i].permissions_for(interaction.user).read_messages:
            channel_total += 1
            has_permission_to_channel.append(interaction.guild.text_channels[i])

    await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> 0% กำลังเริ่มต้น...ตรวจพบ {channel_total} ช่อง**")
    print(f"ดึงข้อความโดย {interaction.user.name} ตรวจพบ {channel_total} ช่อง")
    # LOOP CHANNEL
    for channel in has_permission_to_channel:
        print(f"กำลังดึงข้อมูลจาก {channel}")
        percent_total = round((channel_count / channel_total) * 100, 1)

        stop_button = discord.ui.Button(label="Stop",style=discord.ButtonStyle.red)
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
                f.write(f"{message.author} ({message.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%d/%m/%Y - %H:%M:%S')}): {message.content}\n") # Write line to file
                
                # AFTER WRITE
                current_msg += 1
                # CHECK IF USER CLICK STOP BUTTON
                if client.force_stop[guild] == True :
                    break
            channel_count += 1 # After finish save message in channel
            if client.force_stop[guild] == True :
                break 
    
    # MAKE ZIP FILE
    if client.force_stop[guild] == False :
        await interaction.edit_original_response(content=f"**<a:AppleLoadingGIF:1052465926487953428> กำลังบีบอัดไฟล์...**")
        print("Making zip file...")
        shutil.make_archive(f"{interaction.guild_id}_{interaction.user.id}", 'zip', 'asset/chat')
        shutil.move(f"{interaction.guild_id}_{interaction.user.id}.zip", f"asset/chat/{interaction.guild_id}_{interaction.user.id}.zip")
        print("Zip file complete")

        # DOWNLOAD BUTTON
        download_button = discord.ui.Button(label="Download",emoji="📥",style=discord.ButtonStyle.green)
        async def download_callback(interaction):
            try:
                file = discord.File(f"asset/chat/{interaction.guild_id}_{interaction.user.id}.zip")
                await interaction.response.send_message(file=file)
            except:
                await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")
                await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))
        
        download_button.callback = download_callback
        view = discord.ui.View()
        view.add_item(download_button)

    # END LOOP CHANNEL
    end_time = time.time()
    if client.overtime[guild] == False:
        if client.force_stop[guild] == False :
            await interaction.edit_original_response(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=view)
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))
        elif client.force_stop[guild] == True:
            await interaction.edit_original_response(content=f"**🛑 การดึงข้อความถูกยกเลิก**",view=None)
            await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="🛑"))
    elif client.overtime[guild] == True and client.force_stop[guild] == False:
        await channel.send(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'asset/chat')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=view)
        await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))


# Get Info
@client.tree.command(name='user', description="👤 ดูข้อมูลของผู้ใช้")
async def user(interaction: discord.Interaction, member: Optional[discord.User]):
    if member == None:
        log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction))
    else:
        log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction, member))

    user = interaction.guild.get_member(interaction.user.id)
    if member != None:
        user = interaction.guild.get_member(member.id)

    # Separate guilds by comma
    if user.bot == False:
        mutual_guilds = "\n> ".join([f"`{guild.name}`" for guild in user.mutual_guilds])
        len_mutual_guilds = len(user.mutual_guilds)
    else:
        mutual_guilds = "`ไม่มี`"
        len_mutual_guilds = "-"

    # Status
    status = "ออฟไลน์"
    if user.status == discord.Status.online:
        status = "<:Online:1094241869183074404> ออนไลน์"
    elif user.status == discord.Status.idle:
        status = "<:Away:1094241859418722405> ไม่อยู่"
    elif user.status == discord.Status.dnd:
        status = "<:DND:1094241861394251787> ห้ามรบกวน"
    elif user.status == discord.Status.offline:
        status = "<:Offline:1094241865773092914> ออฟไลน์"
        
    # Activity
    if user.activity != None:
        if user.activity.type == discord.ActivityType.playing:
            activity = f"`กำลังเล่น {user.activity.name}`"
        elif user.activity.type == discord.ActivityType.streaming:
            activity = f"`กำลังสตรีม {user.activity.name}`"
        elif user.activity.type == discord.ActivityType.listening:
            activity = f"`กำลังฟัง {user.activity.name}`"
        elif user.activity.type == discord.ActivityType.watching:
            activity = f"`กำลังดู {user.activity.name}`"
        elif user.activity.type == discord.ActivityType.custom:
            activity = f"`กำลังทำอะไรบางอย่าง`"
    else:
        activity = "`ไม่มีกิจกรรม`"

    # Check client status
    client_status1 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 📱 อุปกรณ์พกพา"
    client_status2 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 🖥️ เดสก์ท็อป"
    client_status3 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 🌐 เว็บ"
    if user.mobile_status == discord.Status.online or user.mobile_status == discord.Status.idle or user.mobile_status == discord.Status.dnd:
        client_status1 = "<:Online:1094241869183074404>  ออนไลน์บน : 📱 อุปกรณ์พกพา"
    if user.desktop_status == discord.Status.online or user.desktop_status == discord.Status.idle or user.desktop_status == discord.Status.dnd:
        client_status2 = "<:Online:1094241869183074404>  ออนไลน์บน : 🖥️ เดสก์ท็อป"
    if user.web_status == discord.Status.online or user.web_status == discord.Status.idle or user.web_status == discord.Status.dnd:
        client_status3 = "<:Online:1094241869183074404>  ออนไลน์บน : 🌐 เว็บ"

    # Extract flags
    user_flags = user.public_flags.value
    badge_info = [
        ("<:staff:1094257629531996250>Discord Staff", discord.PublicUserFlags.staff.flag),
        ("<:icon_partneredserverowner:1094258897482690590> `Discord Partner`", discord.PublicUserFlags.partner.flag),
        ("<:Badge_HypeSquadEvents:1094259133571682507> `HypeSquad Events`", discord.PublicUserFlags.hypesquad.flag),
        ("<:discord_bughunterlv1:1094259250936696873> `Bug Hunter Level 1`", discord.PublicUserFlags.bug_hunter.flag),
        ("<:icon_hypesquadbravery:1094259446609350736> `House Bravery`", discord.PublicUserFlags.hypesquad_bravery.flag),
        ("<:icon_hypesquadbrilliance:1094259551831855204> `House Brilliance`", discord.PublicUserFlags.hypesquad_brilliance.flag),
        ("<:icon_hypesquadbalance:1094259581544312923> `House Balance`", discord.PublicUserFlags.hypesquad_balance.flag),
        ("<:Badge_EarlySupporter:1094259813472551013> `Early Supporter`", discord.PublicUserFlags.early_supporter.flag),
        ("`Team User`", discord.PublicUserFlags.team_user.flag),
        ("`System`", discord.PublicUserFlags.system.flag),
        ("<:BugHunterLvl2:1094259304212742234> `Bug Hunter Level 2`", discord.PublicUserFlags.bug_hunter_level_2.flag),
        ("`Verified Bot`", discord.PublicUserFlags.verified_bot.flag),
        ("<:Early_Verified_Bot_Developer:1094260288712355931> `Verified Bot Developer`", discord.PublicUserFlags.verified_bot_developer.flag),
        ("<:Certified_Moderator:1094260591490764962> `Discord Certified Moderator`", discord.PublicUserFlags.discord_certified_moderator.flag),
        ("`Bot HTTP Interactions`", discord.PublicUserFlags.bot_http_interactions.flag),
        ("`Spammer`", discord.PublicUserFlags.spammer.flag),
        ("<:Active_Developer_Badge:1094260754686935070> `Active Developer`", discord.PublicUserFlags.active_developer.flag),
    ]
    badges = [name for name, flag in badge_info if user_flags & flag]
    message = "\n> ".join(badges)
    if message == "":
        message = "`ไม่มี`"

    # Create embed
    embed = discord.Embed(title=f"ข้อมูลของ {user.name}#{user.discriminator}", color=0x0091ff)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.description = f"ไอดีของบัญชี : `{user.id}`\nข้อมูลจากเซิร์ฟเวอร์ : `{interaction.guild.name} ({interaction.guild_id})`"
    embed.add_field(name="**ชื่อเล่น**", value=f"`{user.display_name}`")
    embed.add_field(name="**สร้างบัญชีเมื่อ**", value=f'{user.created_at.strftime("`วันที่ %d/%m/%Y` `เวลา %H:%M:%S`")}')
    embed.add_field(name="**เข้าร่วมเซิร์ฟเวอร์เมื่อ**", value=f'{user.joined_at.strftime("`วันที่ %d/%m/%Y` `เวลา %H:%M:%S`")}')
    embed.add_field(name="**กิจกรรม**", value=activity)
    embed.add_field(name=f"**เซิร์ฟเวอร์ร่วมกับบอท : {len_mutual_guilds} เซิร์ฟเวอร์**", value=f"> {mutual_guilds}")
    embed.add_field(name="**เหรียญตรา**", value=f"> {message}")
    embed.add_field(name=f"**สถานะ :  {status}**", value=f"**{client_status1}\n{client_status2}\n{client_status3}**")
    embed.timestamp = interaction.created_at
    await interaction.response.send_message(embed=embed)
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))

# AI COMMAND
@client.tree.command(name='ai', description="🧠 เปิด/ปิดการคุยกับบอท")
@app_commands.choices(mode=[
    app_commands.Choice(name="Speak (Voice listening is not yet supported)",value="speak"),
    app_commands.Choice(name="Chat",value="chat"),
    app_commands.Choice(name="Reset the chat history",value="reset"),
    app_commands.Choice(name="Turn Off ❌",value="off"),])

@app_commands.describe(mode="เลือกโหมดที่ต้องการ", language="เลือกภาษาที่ต้องการให้พูด (Only neural voices is supported)")
async def ai(interaction: discord.Interaction, mode: discord.app_commands.Choice[str], language: Optional[str]):
    log_msg = await InfomationLog.sendlog(self=InfomationLog(interaction, mode.name)) # ขี้เกียจเก็บภาษา
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
                await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="⚠️"))
        
        elif client.talk_to_ai[guild] == 2:
            voice_channel = interaction.user.voice.channel
            await interaction.response.send_message(f"**ℹ️ บอทกำลังคุยอยู่ใน <#{voice_channel.id}>**")

    elif mode.value == 'reset':
        if client.chat_history[guild] != client.first_yuuka_prompt:
            client.chat_history[guild] = client.first_yuuka_prompt
            await interaction.response.send_message("**✅ ล้างประวัติการคุยแล้ว**")
        else:
            await interaction.response.send_message("**❌ ไม่มีประวัติการคุย**")
    
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
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))


# Context Menu
@client.tree.context_menu(name='Search by Image')
async def searchbyimage(interaction: discord.Interaction, message: discord.Message):
    # Only for last image (Fix later)
    #try:
    log_msg = await InfomationLog.contextlog(self=InfomationLog(interaction,message))
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
    url_view.add_item(discord.ui.Button(label='Result',emoji="🔎",style=discord.ButtonStyle.url, url=img_search_url))

    await interaction.response.send_message(embed=search, view=url_view)
    #except:
    #    await interaction.response.send_message("**❌ ไฟล์หมดอายุแล้ว**")
    await InfomationLog.runcomplete(self=InfomationLog(interaction, log_msg=log_msg, log_data="<:Approve:921703512382009354>"))


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
            # If the bot is already speaking, stop it
            if voice.is_playing():
                voice.stop()
            speech_synthesis.tts(response.replace("Yuuka: ", ""), client.voice_language[guild], client.ai_active_channel[guild])
            voice.play(discord.FFmpegPCMAudio(f"temp/{client.ai_active_channel[guild]}_output.wav"))

@client.event
async def on_error(interaction, error):
    channel = client.get_channel(1003719893260185750)
    errors = []
    errors.append(error)
    error_log = discord.Embed(title=f"⚠️ **Error**", color=0xff0000)
    str_error = '\n'.join(errors)
    error_log.add_field(name="ข้อผิดพลาด",value=f"```{str_error}```")
    log_button = discord.ui.View()
    log_button.add_item(discord.ui.Button(label='Log',emoji="📝",style=discord.ButtonStyle.url, url="https://dashboard.heroku.com/apps/yuuka-discordbot/logs"))
    await channel.send(embed=error_log, view=log_button)
    raise Exception(str_error)
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
    dir2 = 'asset/chat'
    for f in os.listdir(dir):
        os.remove(os.path.join(dir, f))
    for f in os.listdir(dir2):
        os.remove(os.path.join(dir2, f))

Token = os.environ['YuukaToken']
client.run(Token)