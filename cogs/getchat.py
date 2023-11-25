import discord
from discord.ext import commands
from discord import app_commands
import os
import time
import shutil
import pytz
import utils.filesize as filesize
import utils.sectobigger as sectobigger

class GetChat(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.force_stop = {}
        self.overtime = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print("GetChat cog loaded")

    @app_commands.command(name='getchat', description="🗞️ บันทึกประวัติการส่งข้อความ")
    async def getchat(self, interaction: discord.Interaction):
        await self.log_cog.sendlog(interaction)
        
        try:
            os.mkdir(f'temp/chat/{interaction.guild_id}')
        except FileExistsError:
            pass
        # DELETE FILE
        dir = f'temp/chat/{interaction.guild_id}/'
        for f in os.listdir(dir):
            os.remove(os.path.join(dir, f))

        channel = interaction.channel
        start_time = time.time()
        guild = interaction.guild_id
        self.force_stop[guild] = False
        self.overtime[guild] = False
        channel_count = 0
        has_permission_to_channel = []

        # GET TOTAL CHANNEL WITH PERMISSION
        channel_total = 0
        for i in range(len(interaction.guild.text_channels)):
            if interaction.guild.text_channels[i].permissions_for(interaction.user).read_messages:
                channel_total += 1
                has_permission_to_channel.append(interaction.guild.text_channels[i])

        await interaction.response.send_message(f"**<a:AppleLoadingGIF:1052465926487953428> 0% กำลังเริ่มต้น...ตรวจพบ {channel_total} ช่อง**")
        print(f"ดึงข้อความด้วยสิทธิของ {interaction.user.name} ตรวจพบ {channel_total} ช่อง")
        # LOOP CHANNEL
        for channel in has_permission_to_channel:
            print(f"กำลังดึงข้อมูลจาก {channel}")
            percent_total = round((channel_count / channel_total) * 100, 1)

            stop_button = discord.ui.Button(label="Stop",style=discord.ButtonStyle.red)
            async def stop_callback(interaction):
                self.force_stop[guild] = True

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
            if os.path.exists(f"temp/chat/{interaction.guild_id}/{channel.id}.txt") == True:
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
            with open(f"temp/chat/{interaction.guild_id}/{channel.id}.txt", "w", encoding="utf-8") as f:
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
                            self.overtime[guild] = True
                    # WHILE WRITE
                        # f.write takes too much time for update progress in discord
                        # Means it will update every time a single line is written.
                    f.write(f"{message.author} ({message.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%d-%m%Y %H:%M:%S')}): {message.content}\n") # Write line to file
                    
                    # AFTER WRITE
                    current_msg += 1
                    # CHECK IF USER CLICK STOP BUTTON
                    if self.force_stop[guild] == True :
                        break
                channel_count += 1 # After finish save message in channel
                if self.force_stop[guild] == True :
                    break 
        
        # MAKE ZIP FILE
        if self.force_stop[guild] == False :
            await interaction.edit_original_response(content=f"**<a:AppleLoadingGIF:1052465926487953428> กำลังบีบอัดไฟล์...**")
            print("Making zip file...")
            shutil.make_archive(f"{interaction.guild_id}_{interaction.user.id}", 'zip', f'temp/chat/{interaction.guild_id}')
            shutil.move(f"{interaction.guild_id}_{interaction.user.id}.zip", f"temp/chat/{interaction.guild_id}/{interaction.guild_id}_{interaction.user.id}.zip")
            print("Zip file complete")

            # DOWNLOAD BUTTON
            download_button = discord.ui.Button(label="Download",emoji="📥",style=discord.ButtonStyle.green)
            async def download_callback(interaction):
                try:
                    file = discord.File(f"temp/chat/{interaction.guild_id}/{interaction.guild_id}_{interaction.user.id}.zip")
                    await interaction.response.send_message(file=file)
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")
                    await self.log_cog.runcomplete('⚠️')
            
            download_button.callback = download_callback
            view = discord.ui.View()
            view.add_item(download_button)

        # END LOOP CHANNEL
        end_time = time.time()
        if self.overtime[guild] == False:
            if self.force_stop[guild] == False :
                await interaction.edit_original_response(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'temp/chat/{interaction.guild_id}')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=view)
                await self.log_cog.runcomplete('<:Approve:921703512382009354>')
            elif self.force_stop[guild] == True:
                await interaction.edit_original_response(content=f"**🛑 การดึงข้อความถูกยกเลิก**",view=None)
                await self.log_cog.runcomplete('🛑')
        elif self.overtime[guild] == True and self.force_stop[guild] == False:
            await channel.send(content=f"**✅ ดึงข้อความเสร็จสิ้น `({filesize.getfoldersize(f'temp/chat/{interaction.guild_id}')})` ใช้เวลา `{sectobigger.sec(round(end_time - start_time, 2))}`**",view=view)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up GetChat cog")
    await client.add_cog(GetChat(client))