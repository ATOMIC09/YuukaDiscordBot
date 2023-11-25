import discord
from discord.ext import commands
from discord import app_commands
import utils.get_meme as get_meme
import utils.video as video

class Meme(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Meme cog loaded")

    @app_commands.command(name='meme', description="😂 สุ่มวิดีโอมีม")
    async def meme(self, interaction: discord.Interaction):
        await interaction.response.send_message("<a:AppleLoadingGIF:1052465926487953428> **กำลังหามีม...**")
        meme_data = await get_meme.get_reddit()
        if meme_data is None:
            await interaction.edit_original_response(content="❌ **ไม่สามารถโหลดมีมได้ในขณะนี้**")
            return
        video_url, audio_url, video_name, post_link = meme_data
        await interaction.edit_original_response(content=f"<a:AppleLoadingGIF:1052465926487953428> **กำลังโหลดมีม...** {video_name}")
        await self.log_cog.sendlog(interaction, data={'content': f"{video_name}\n\n{post_link}"})
        status = video.mix(video_url, audio_url, video_name)
        if '403' and 'Video' in status:
            await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... (Video URL 403 Forbidden: Access Denied)**")
            await self.log_cog.runcomplete('⚠️')
            return
        elif '403' and 'Audio' in status:
            await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... (Audio URL 403 Forbidden: Access Denied)**")
            
            async def download_video_only(interaction):
                await interaction.response.send_message(content=f"<a:AppleLoadingGIF:1052465926487953428> **กำลังโหลดมีม (เฉพาะวิดีโอ)...** {video_name}")
                try:
                    status = video.download_video_only(video_url, video_name)
                    if '403' and 'Video' in status:
                        await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... (Video URL 403 Forbidden: Access Denied)**")
                        await self.log_cog.runcomplete('⚠️')
                        return
                    elif 'Success' in status:
                        await interaction.followup.send(file=discord.File(f"temp/video/{video_name}.mp4"))
                        await interaction.edit_original_response(content=f"✅ **ส่งมีมแล้ว...** {video_name}")
                        await self.log_cog.runcomplete('<:Approve:921703512382009354>')
                    else:
                        await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... ไม่นะ! บางอย่างผิดปกติ**")
                        await self.log_cog.runcomplete('⚠️')
                        return
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")
            download_video_only_btn = discord.ui.Button(label="Video Only (No sound)", emoji="🔇", style=discord.ButtonStyle.primary, custom_id="video_only")
            download_video_only_btn.callback = download_video_only
            original_url = discord.ui.View()
            original_url.add_item(discord.ui.Button(label="Source", emoji="🔗", style=discord.ButtonStyle.url, url=post_link))
            original_url.add_item(download_video_only_btn)

            await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... (Audio URL 403 Forbidden: Access Denied)**", view=original_url)
            await self.log_cog.runcomplete('⚠️')
            return
        
        elif 'Success' in status:
            await interaction.followup.send(file=discord.File(f"temp/video/{video_name}.mp4"))

            url = discord.ui.View()
            url.add_item(discord.ui.Button(label="Source", emoji="🔗", style=discord.ButtonStyle.url, url=post_link))
            await interaction.edit_original_response(content=f"✅ **ส่งมีมแล้ว...** {video_name}", view=url)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
            
        else:
            await interaction.edit_original_response(content=f"❌ **ไม่สามารถโหลดมีม** {video_name} **ได้... ไม่นะ! บางอย่างผิดปกติ**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client: commands.Bot):
    print("Setting up Meme cog")
    await client.add_cog(Meme(client))