import discord
from discord.ext import commands
from discord import app_commands
import utils.video_processing as video_processing
import utils.img_processing as img_processing
import utils.filesize as filesize
# from pymediainfo import MediaInfo

class ImgAudio(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("ImgAudio cog loaded")

    @app_commands.command(name='imgaudio', description="🎵 สร้างคลิปเสียงจากภาพ")
    async def imgaudio(self, interaction: discord.Interaction):
        # Get last media from channel
        channel = self.client.get_channel(interaction.channel_id)
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังค้นหามีเดีย...**")

        attachment_list = [message.attachments async for message in channel.history(limit=5)]
        full_messages_list = [message async for message in channel.history(limit=5)]

        filename1 = ""
        url1 = ""
        filename2 = ""
        url2 = ""
        message1 = None
        message2 = None
        found_media = 0
        count = 0
        
        # Check is the last media is audio or image
        for attachment in attachment_list:
            try:
                file_name = attachment[0].filename
                url = attachment[0].url
                if found_media == 0:
                    filename1 = file_name
                    url1 = url
                    message1 = full_messages_list[count+1]
                    found_media += 1
                elif found_media == 1:
                    filename2 = file_name
                    url2 = url
                    message2 = full_messages_list[count+1]
                    found_media += 1
                elif found_media == 2:
                    found_media == 0
                    break
                count += 1
                
            except AttributeError: # Empty attachment list (Have message but no attachment)
                continue

            except IndexError: # Empty message list (No message)
                continue
        
        await self.log_cog.sendlog(interaction, data={'content': f"{filename1} + {filename2}"})
        
        await interaction.edit_original_response(content="<a:AppleLoadingGIF:1052465926487953428> **กำลังสร้าง...**")
        
        path = ""

        if filename1.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff')):
            # Save the image
            image_path = img_processing.save_image_from_url(url1, f"temp/image/{filename1}")
            await message1.add_reaction("🖼️")
            # Save the audio
            audio_path = img_processing.save_image_from_url(url2, f"temp/audio/{filename2}")
            await message2.add_reaction("🔊")
            # Process the video
            video_processing.add_static_image_to_audio(image_path, audio_path, f"temp/video/{filename1.split('.')[0]}_{filename2.split('.')[0]}.mp4")
            path = f"temp/video/{filename1.split('.')[0]}_{filename2.split('.')[0]}.mp4"



        elif filename1.endswith(('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.wma', '.aac', '.opus', '3gp', 'mp4')):
            # Save the audio
            audio_path = img_processing.save_image_from_url(url1, f"temp/audio/{filename1}")
            await message1.add_reaction("🔊")
            # Save the image
            image_path = img_processing.save_image_from_url(url2, f"temp/image/{filename2}")
            await message2.add_reaction("🖼️")
            # Process the video
            video_processing.add_static_image_to_audio(image_path, audio_path, f"temp/video/{filename2.split('.')[0]}_{filename1.split('.')[0]}.mp4")
            path = f"temp/video/{filename2.split('.')[0]}_{filename1.split('.')[0]}.mp4"


        # Send the video
        file_name = discord.File(path)
        await interaction.edit_original_response(content=f"✅ **สร้างเสร็จแล้ว `({filesize.getsize(path)})`**")
        await interaction.followup.send(file=file_name)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up ImgAudio cog")
    await client.add_cog(ImgAudio(client))