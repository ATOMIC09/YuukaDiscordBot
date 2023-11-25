import discord
from discord.ext import commands
from discord import app_commands
import utils.ytdlp as ytdlp
import utils.shorten_url as shorturl
import utils.sectobigger as sectobigger

class Youtube(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Youtube cog loaded")

    @app_commands.command(name="youtube",description="🎬 ขอไฟล์จาก Youtube (Not functional)")
    @app_commands.describe(url="ใส่ URL ของคลิปใน Youtube")
    async def youtube_def(self, interaction: discord.Interaction, url: str):
        await self.log_cog.sendlog(interaction, data={'content': f"{url}"})
        await interaction.response.send_message(f"<a:MagnifierGIF:1052563354910216252> **กำลังหา** `{url}`")

        info = ytdlp.get_video_info(url)
        title = info['title']
        ext = info['ext']
        upload_date = info['upload_date']
        uploader = info['uploader']
        uploader_id = info['uploader_id']
        channel_id = info['channel_id']
        channel_follower_count = info['channel_follower_count']
        duration = info['duration']
        view_count = info['view_count']
        like_count = info['like_count']
        comment_count = info['comment_count']
        filesize_approx = info['filesize_approx']
        resolution = info['resolution']
        fps = info['fps']
        original_url = info['original_url']

        videolink = ytdlp.get_video_url(url)
        audiolink = ytdlp.get_audio_url(url)
        thumbnail = info['thumbnail']

        videolinknew = shorturl.shortenmylink(videolink)
        audiolinknew = shorturl.shortenmylink(audiolink)
        durationnew = sectobigger.sec(duration)
        upload_datenew = sectobigger.datenumbeautiful(upload_date)
        if comment_count == None:
            comment_count = "N/A"
        else:
            comment_count = str(comment_count) + " ความคิดเห็น"
        if like_count != "N/A":
            like_count = str(like_count) + " คน"

        dl = discord.Embed(title = f"**{title}**", color = 0xff80c9)
        dl.timestamp = interaction.created_at
        dl.add_field(name="🔐 นามสกุลไฟล์", value=f"`{ext}`", inline=True)
        dl.add_field(name="📐 ความละเอียด", value=f"`{resolution}`", inline=True)
        dl.add_field(name="🖼️ เฟรมเรท", value=f"`{fps} FPS`", inline=True)
        dl.add_field(name="🧑 ผู้อัปโหลด", value=f"`{uploader}` `({uploader_id})`", inline=True)
        dl.add_field(name="📺 ไอดีช่อง", value=f"`{channel_id}`", inline=True)
        dl.add_field(name="👀 ผู้ติดตาม", value=f"`{channel_follower_count} คน`", inline=True)
        dl.add_field(name="📆 วันที่อัปโหลด", value=f"`{upload_datenew}`", inline=True)
        dl.add_field(name="🕒 ระยะเวลา", value=f"`{durationnew}`", inline=True)
        dl.add_field(name="👀 จำนวนคนดู", value=f"`{view_count} คน`", inline=True)
        dl.add_field(name="👍🏻 จำนวนคน Like", value=f"`{like_count}`", inline=True)
        dl.add_field(name="💬 จำนวน Comment", value=f"`{comment_count}`", inline=True)
        dl.add_field(name="📦 ขนาดไฟล์", value=f"`{filesize_approx}`", inline=True)
        dl.set_image(url=thumbnail)

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Video',emoji="🎬" , style=discord.ButtonStyle.url, url=videolinknew))
        url_view.add_item(discord.ui.Button(label='Audio',emoji="🔊" , style=discord.ButtonStyle.url, url=audiolinknew))
        url_view.add_item(discord.ui.Button(label='Play on Youtube',emoji="▶️" , style=discord.ButtonStyle.url, url=original_url))
        url_view.add_item(discord.ui.Button(label='Subscribe',emoji="🔔" , style=discord.ButtonStyle.url, url=f"https://www.youtube.com/channel/{channel_id}?sub_confirmation=1"))

        await interaction.edit_original_response(content="",embed=dl,view=url_view)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Youtube cog")
    await client.add_cog(Youtube(client))