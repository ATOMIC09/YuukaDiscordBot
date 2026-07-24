import asyncio
import collections
import dataclasses
from concurrent.futures import ThreadPoolExecutor

import discord
import yt_dlp

try:
    from yt_dlp.extractor.youtube.jsc._builtin import ejs
except ImportError:
    pass
from discord.ext import commands

from bot.logger import logger
from utils.embeds import success_embed, error_embed, info_embed
from utils.errors import UserError

yt_dlp.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'extract_flat': 'in_playlist',
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'options': '-vn',
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

@dataclasses.dataclass
class Track:
    title: str
    duration: int
    thumbnail: str
    requester: discord.User | discord.Member
    original_url: str
    stream_url: str | None = None
    uploader: str | None = None
    view_count: int | None = None
    cover_bytes: bytes | None = None
    like_count: int | None = None
    comment_count: int | None = None
    upload_date: str | None = None
    album: str | None = None
    year: str | None = None
    channel_follower_count: int | None = None
    filesize: int | None = None
    bitrate: float | None = None

class AudioState:
    def __init__(self, bot: discord.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue: collections.deque[Track] = collections.deque()
        self.current: Track | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.loop_mode: str = "off"  # "off", "track", "queue"
        self.volume: float = 1.0
        self.is_playing_loop: bool = False
        self.skip_request: bool = False
        self.last_controller_message: discord.WebhookMessage | discord.Message | None = None
        self.text_channel: discord.TextChannel | discord.Thread | None = None
        self.idle_task: asyncio.Task | None = None

class PlayerControls(discord.ui.View):
    def __init__(self, cog: "PlayerCog", state: "AudioState"):
        super().__init__(timeout=None)
        self.cog = cog
        self.state = state
        self.update_buttons()

    def update_buttons(self):
        if self.state.voice_client and self.state.voice_client.is_paused():
            self.pause_resume.emoji = "▶️"
            self.pause_resume.style = discord.ButtonStyle.primary
        else:
            self.pause_resume.emoji = "⏸️"
            self.pause_resume.style = discord.ButtonStyle.success
            
        if self.state.loop_mode == "off":
            self.loop.emoji = "➡️"
            self.loop.style = discord.ButtonStyle.secondary
        elif self.state.loop_mode == "track":
            self.loop.emoji = "🔂"
            self.loop.style = discord.ButtonStyle.primary
        elif self.state.loop_mode == "queue":
            self.loop.emoji = "🔁"
            self.loop.style = discord.ButtonStyle.success

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("หนูไม่เห็นเซนเซย์ในห้องเสียงเลยนะคะ (´・ω・)", ephemeral=True)
            return False
        if self.state.voice_client and interaction.user.voice.channel.id != self.state.voice_client.channel.id:
            await interaction.response.send_message("เซนเซย์อยู่คนละห้องกับหนูนะคะ (・`ω´・)", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⏸️")
    async def pause_resume(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.state.voice_client:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)
            
        if self.state.voice_client.is_paused():
            self.state.voice_client.resume()
        elif self.state.voice_client.is_playing():
            self.state.voice_client.pause()
        else:
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่นะคะ", ephemeral=True)
            
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not self.state.voice_client or not self.state.voice_client.is_playing():
            return await interaction.response.send_message("ไม่มีเพลงเล่นอยู่ให้ข้ามนะคะ", ephemeral=True)
        
        self.state.skip_request = True
        self.state.voice_client.stop()
        await interaction.response.defer()
        
    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="➡️")
    async def loop(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.state.loop_mode == "off":
            self.state.loop_mode = "queue"
        elif self.state.loop_mode == "queue":
            self.state.loop_mode = "track"
        else:
            self.state.loop_mode = "off"
            
        self.update_buttons()
        
        embed = self.cog._build_player_embed(self.state.current, self.state)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.state.queue.clear()
        self.state.loop_mode = "off"
        self.state.last_controller_message = None
            
        if self.state.voice_client and self.state.voice_client.is_playing():
            self.state.voice_client.stop()
            
        try:
            embeds = interaction.message.embeds
            if embeds:
                embeds[0].color = discord.Color.dark_theme()
                embeds[0].description = None
                await interaction.response.edit_message(embed=embeds[0], view=None)
            else:
                await interaction.response.edit_message(view=None)
        except Exception:
            pass
            
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.state.last_controller_message:
            try:
                await self.state.last_controller_message.edit(view=self)
            except Exception:
                pass

import math

class QueuePaginator(discord.ui.View):
    def __init__(self, state: "AudioState", items_per_page: int = 30):
        super().__init__(timeout=300)
        self.state = state
        self.items_per_page = items_per_page
        self.current_page = 1
        self.total_pages = max(1, math.ceil(len(self.state.queue) / self.items_per_page))
        self.update_buttons()
        
    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎶 คิวเพลงทั้งหมด", color=discord.Color.blurple())
        
        desc = ""
        if self.state.current:
            mins, secs = divmod(self.state.current.duration, 60)
            dur_str = f"{mins}:{secs:02d}" if self.state.current.duration > 0 else "Live/Unknown"
            desc += f"**▶️ กำลังเล่น:** [{self.state.current.title}]({self.state.current.original_url}) `[{dur_str}]`\n\n"
            
        if len(self.state.queue) == 0:
            desc += "*คิวว่างเปล่าค่ะ*"
            embed.description = desc
            return embed
            
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        queue_slice = list(self.state.queue)[start_idx:end_idx]
        
        for i, track in enumerate(queue_slice, start=start_idx + 1):
            mins, secs = divmod(track.duration, 60)
            dur_str = f"{mins}:{secs:02d}" if track.duration > 0 else "Live/Unknown"
            title = track.title
            if len(title) > 50:
                title = title[:47] + "..."
            desc += f"{i}. [{title}]({track.original_url}) `[{dur_str}]` - {track.requester.mention}\n"
            
        embed.description = desc
        embed.set_footer(text=f"หน้า {self.current_page}/{self.total_pages} | ทั้งหมด {len(self.state.queue)} เพลง")
        return embed
        
    def update_buttons(self):
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages
        
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
        
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

class PlayerCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.states: dict[int, AudioState] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    def get_state(self, guild_id: int) -> AudioState:
        if guild_id not in self.states:
            self.states[guild_id] = AudioState(self.bot, guild_id)
        return self.states[guild_id]
        
    def _build_player_embed(self, track: Track, state: AudioState) -> discord.Embed:
        embed = discord.Embed(
            title=track.title,
            url=track.original_url,
            color=discord.Color(0x5865F2)
        )
        if track.thumbnail:
            embed.set_image(url=track.thumbnail)
        elif track.cover_bytes:
            embed.set_image(url="attachment://cover.jpg")
            
        if track.uploader:
            embed.add_field(name="🎤 ศิลปิน", value=f"`{track.uploader}`", inline=False)
        if track.album:
            embed.add_field(name="💿 อัลบั้ม", value=f"`{track.album}`", inline=False)

        mins, secs = divmod(track.duration, 60)
        dur_str = f"{mins}:{secs:02d}" if track.duration > 0 else "Live/Unknown"
        embed.add_field(name="⏳ ความยาว", value=f"`{dur_str}`", inline=True)
        embed.add_field(name="👤 ขอโดย", value=track.requester.mention, inline=True)
            
        if track.view_count or track.like_count or track.comment_count:
            if track.view_count:
                embed.add_field(name="👀 ยอดวิว", value=f"`{track.view_count:,}`", inline=True)
            if track.like_count:
                embed.add_field(name="👍 ยอดไลก์", value=f"`{track.like_count:,}`", inline=True)
            if track.comment_count:
                embed.add_field(name="💬 คอมเมนต์", value=f"`{track.comment_count:,}`", inline=True)
                
        if track.upload_date or track.channel_follower_count:
            if track.upload_date and len(track.upload_date) == 8:
                date_str = f"{track.upload_date[6:8]}/{track.upload_date[4:6]}/{track.upload_date[0:4]}"
                embed.add_field(name="📅 วันที่ลง", value=f"`{date_str}`", inline=True)
            if track.channel_follower_count:
                embed.add_field(name="👥 ผู้ติดตาม", value=f"`{track.channel_follower_count:,}`", inline=True)
                
        if track.year or track.filesize or track.bitrate:
            
            if track.year:
                embed.add_field(name="🗓️ ปี", value=f"`{track.year}`", inline=True)
            if track.filesize:
                mb = track.filesize / (1024 * 1024)
                embed.add_field(name="💾 ขนาดไฟล์", value=f"`{mb:.2f} MB`", inline=True)
            if track.bitrate:
                embed.add_field(name="🎵 บิตเรต", value=f"`{int(track.bitrate)} kbps`", inline=True)
        
        # Append queue
        desc = ""
        if len(state.queue) > 0:
            desc += "**🎶 คิวถัดไป:**\n"
            for i, qtrack in enumerate(list(state.queue)):
                if i < 5:
                    mins, secs = divmod(qtrack.duration, 60)
                    desc += f"{i+1}. [{qtrack.title}]({qtrack.original_url}) `[{mins}:{secs:02d}]` - {qtrack.requester.mention}\n"
            if len(state.queue) > 5:
                desc += f"\n*...และอีก {len(state.queue) - 5} เพลง*"
                
        if desc:
            embed.description = desc
            
        loop_th = {"off": "ปิด", "track": "เพลงเดียว", "queue": "ทั้งคิว"}.get(state.loop_mode, state.loop_mode)
        embed.set_footer(text=f"🔁 วนลูป: {loop_th}  |  🔊 ระดับเสียง: {int(state.volume * 100)}%")
            
        return embed

    async def _update_controller(self, state: AudioState, embed: discord.Embed):
        view = PlayerControls(self, state)
        
        file = None
        # Only upload if we have cover_bytes and NO thumbnail yet.
        if state.current and state.current.cover_bytes and not state.current.thumbnail:
            import io
            file = discord.File(io.BytesIO(state.current.cover_bytes), filename="cover.jpg")
            embed.set_image(url="attachment://cover.jpg")
            
        kwargs = {"embed": embed, "view": view}
        
        msg = None
        if state.last_controller_message:
            try:
                edit_kwargs = kwargs.copy()
                if file:
                    edit_kwargs["file"] = file
                    edit_kwargs["attachments"] = []
                else:
                    edit_kwargs["attachments"] = []
                msg = await state.last_controller_message.edit(**edit_kwargs)
            except Exception as e:
                logger.error(f"Error editing controller: {e}")
                
        if not msg and state.text_channel:
            send_kwargs = kwargs.copy()
            if file:
                send_kwargs["file"] = file
            msg = await state.text_channel.send(**send_kwargs)
            state.last_controller_message = msg

        # Cache the thumbnail URL if we just uploaded a file
        if msg and file and state.current:
            if msg.embeds and msg.embeds[0].image.url and msg.embeds[0].image.url.startswith("http"):
                state.current.thumbnail = msg.embeds[0].image.url
                state.current.cover_bytes = None
            elif msg.attachments:
                state.current.thumbnail = msg.attachments[0].url
                state.current.cover_bytes = None

    async def _send_controls(self, state: AudioState, ctx, embed: discord.Embed, edit_original: bool = False):
        if state.last_controller_message:
            try:
                embeds = state.last_controller_message.embeds
                if embeds:
                    embeds[0].color = discord.Color.dark_theme()
                    embeds[0].description = None
                    await state.last_controller_message.edit(embed=embeds[0], view=None)
                else:
                    await state.last_controller_message.edit(view=None)
            except Exception:
                pass
        
        view = PlayerControls(self, state)
        
        file = None
        if state.current and state.current.cover_bytes and not state.current.thumbnail:
            import io
            file = discord.File(io.BytesIO(state.current.cover_bytes), filename="cover.jpg")
            embed.set_image(url="attachment://cover.jpg")

        kwargs = {"embed": embed, "view": view}
        if file:
            kwargs["file"] = file
        
        if edit_original:
            msg = await ctx.interaction.edit_original_response(**kwargs)
            state.last_controller_message = msg
        else:
            msg = await ctx.respond(**kwargs)
            if isinstance(msg, discord.Interaction):
                msg = await msg.original_response()
            state.last_controller_message = msg

        if msg and file and state.current:
            if msg.embeds and msg.embeds[0].image.url and msg.embeds[0].image.url.startswith("http"):
                state.current.thumbnail = msg.embeds[0].image.url
                state.current.cover_bytes = None
            elif msg.attachments:
                state.current.thumbnail = msg.attachments[0].url
                state.current.cover_bytes = None

    async def _extract_info(self, query: str, download: bool = False) -> dict:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            self._executor,
            lambda: ytdl.extract_info(query, download=download)
        )
        return data
        
    async def _idle_disconnect(self, guild_id: int):
        await asyncio.sleep(180)
        state = self.states.get(guild_id)
        if state and state.voice_client and state.voice_client.is_connected():
            await state.voice_client.disconnect()
            state.voice_client = None
            state.queue.clear()
            state.current = None
            if state.text_channel:
                await state.text_channel.send(embed=info_embed("ไปแล้วค่า~", "หนูขอตัวออกก่อนนะคะ เพราะไม่มีเพลงเล่นมา 3 นาทีแล้ว (´・ω・)"))

    async def _play_next_async(self, guild_id: int, auto_send: bool = True):
        state = self.get_state(guild_id)
        if not state.voice_client or not state.voice_client.is_connected():
            state.current = None
            state.queue.clear()
            return

        if state.skip_request:
            state.skip_request = False
        else:
            if state.loop_mode == "track" and state.current:
                state.queue.appendleft(state.current)
            elif state.loop_mode == "queue" and state.current:
                state.queue.append(state.current)

        if len(state.queue) == 0:
            state.current = None
            if state.last_controller_message:
                try:
                    embeds = state.last_controller_message.embeds
                    if embeds:
                        embeds[0].color = discord.Color.dark_theme()
                        embeds[0].description = None
                        await state.last_controller_message.edit(embed=embeds[0], view=None)
                    else:
                        await state.last_controller_message.edit(view=None)
                except Exception:
                    pass
                state.last_controller_message = None
            
            # Start idle timer
            if not state.idle_task:
                state.idle_task = self.bot.loop.create_task(self._idle_disconnect(guild_id))
            return

        # Cancel idle timer if exists
        if state.idle_task:
            state.idle_task.cancel()
            state.idle_task = None

        track = state.queue.popleft()
        state.current = track

        # JIT extraction for flat playlist tracks
        if not track.stream_url:
            try:
                data = await self._extract_info(track.original_url, download=False)
                if not data:
                    raise Exception("No data returned by yt-dlp (video might be unavailable).")
                track.stream_url = data.get('url')
                track.title = data.get('title', track.title)
                track.thumbnail = data.get('thumbnail', track.thumbnail)
                track.duration = data.get('duration', track.duration)
                uploader = data.get('uploader', track.uploader)
                if 'channel' in data and data['channel'] != uploader:
                    uploader = f"{uploader} ({data['channel']})" if uploader else data['channel']
                track.uploader = uploader
                track.view_count = data.get('view_count', track.view_count)
                track.like_count = data.get('like_count', track.like_count)
                track.comment_count = data.get('comment_count', track.comment_count)
                track.upload_date = data.get('upload_date', track.upload_date)
                track.channel_follower_count = data.get('channel_follower_count', track.channel_follower_count)
            except Exception as e:
                logger.error(f"Error extracting stream url for {track.original_url}: {e}")
                # Skip to next if failed
                self.bot.loop.create_task(self._play_next_async(guild_id))
                return

        if not track.stream_url:
            logger.warning(f"Could not find stream URL for {track.title}, skipping.")
            self.bot.loop.create_task(self._play_next_async(guild_id))
            return

        try:
            audio_source = discord.FFmpegPCMAudio(track.stream_url, **ffmpeg_options)
            volume_source = discord.PCMVolumeTransformer(audio_source, volume=state.volume)
            
            def after_playing(e):
                if e:
                    logger.error(f"Player error in guild {guild_id}: {e}")
                self.bot.loop.create_task(self._play_next_async(guild_id))

            state.voice_client.play(volume_source, after=after_playing)
            logger.info(f"Playing track in guild {guild_id}: {track.title}")
            
            # Auto-update controller if this was an automatic track progression
            if auto_send and state.text_channel:
                embed = self._build_player_embed(track, state)
                await self._update_controller(state, embed)
        except Exception as e:
            logger.error(f"Error playing track in guild {guild_id}: {e}")
            self.bot.loop.create_task(self._play_next_async(guild_id))

    music = discord.SlashCommandGroup("music", "🎵 ระบบเครื่องเล่นเพลง")

    @music.command(name="leave", description="👋 ออกจากห้องเสียง")
    async def leave(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client:
            raise UserError("หนูไม่ได้อยู่ในห้องนะคะ", "หนูไม่ได้อยู่ในห้องเสียงไหนเลยนะคะ (´-ω-`)")

        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        state.loop_mode = "off"
        
        await ctx.voice_client.disconnect()
        state.voice_client = None

        await ctx.respond(embed=success_embed("ไปแล้วค่า~", "หนูออกจากห้องเสียงแล้วนะคะ ไว้เจอกันใหม่น้า! (・`ω´・)"))

    @music.command(name="local", description="📂 เล่นเพลงจากไฟล์แนบหรือประวัติแชท")
    @discord.option("file", description="อัปโหลดไฟล์เพลงที่นี่เลยค่ะ", required=False, type=discord.SlashCommandOptionType.attachment)
    async def local(self, ctx: discord.ApplicationContext, file: discord.Attachment = None):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        
        await ctx.defer(ephemeral=True)

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "เซนเซย์ต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        
        if ctx.voice_client:
            if ctx.voice_client.channel.id != channel.id:
                raise UserError("คนละห้องค่ะ", "เซนเซย์อยู่คนละห้องกับหนูนะคะ มาหาหนูก่อนน้า (・`ω´・)")

        # Find file in history if not provided
        if not file:
            async for msg in ctx.channel.history(limit=50):
                if msg.attachments:
                    for att in msg.attachments:
                        if att.content_type and att.content_type.startswith(('audio/', 'video/')):
                            file = att
                            break
                if file:
                    break
            
            if not file:
                raise UserError("หาไฟล์ไม่เจอค่ะ", "ไม่เจอไฟล์เพลงใน 50 ข้อความล่าสุดเลยค่ะ รบกวนแนบไฟล์มาให้หนูด้วยนะคะ (´・ω・)")



        if file:
            await ctx.interaction.edit_original_response(embed=info_embed("<a:MagnifierGIF:1052563354910216252> กำลังโหลดไฟล์...", f"กำลังเตรียมไฟล์ `{file.filename}` นะคะ รอแป๊บนึงน้า (・`ω´・)"))
            
            import os
            temp_path = f"assets/audio/music/temp_{file.id}_{file.filename}"
            os.makedirs("assets/audio/music", exist_ok=True)
            await file.save(temp_path)
            
            try:
                from tinytag import TinyTag
                tag = TinyTag.get(temp_path, image=True)
                title = tag.title or file.filename
                uploader = tag.artist or "Local File"
                duration = int(tag.duration) if tag.duration else 0
                cover_bytes = tag.get_image()
                album = tag.album
                year = tag.year
                filesize = tag.filesize
                bitrate = tag.bitrate
            except Exception as e:
                logger.error(f"TinyTag error: {e}")
                title = file.filename
                uploader = "Local File"
                duration = 0
                cover_bytes = None
                album = None
                year = None
                filesize = None
                bitrate = None
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                        
            track = Track(
                title=title,
                duration=duration,
                thumbnail="",
                requester=ctx.author,
                original_url=file.url,
                stream_url=file.url,
                uploader=uploader,
                view_count=None,
                cover_bytes=cover_bytes,
                album=album,
                year=year,
                filesize=filesize,
                bitrate=bitrate
            )
            state.queue.append(track)
            
            
            await ctx.interaction.edit_original_response(embed=success_embed("✅ เพิ่มเข้าคิวแล้ว!", f"เพิ่ม `{title}` ลงคิวเรียบร้อยค่ะ! (๑>◡<๑)"))
            
        if not ctx.guild.voice_client:
            state.voice_client = await channel.connect()
            
        if not state.current or not state.voice_client.is_playing():
            self.bot.loop.create_task(self._play_next_async(ctx.guild.id, auto_send=True))
        else:
            display_track = state.current if state.current else track
            embed = self._build_player_embed(display_track, state)
            await self._update_controller(state, embed)

    @music.command(name="play", description="▶️ เปิดเพลงจาก YouTube (รองรับ Playlist)")
    @discord.option("query", description="ชื่อเพลงหรือ URL ของวิดีโอ/เพลย์ลิสต์ค่ะ")
    async def play(self, ctx: discord.ApplicationContext, query: str):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        
        await ctx.defer(ephemeral=True)

        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "เซนเซย์ต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        
        if ctx.voice_client:
            if ctx.voice_client.channel.id != channel.id:
                raise UserError("คนละห้องค่ะ", "เซนเซย์อยู่คนละห้องกับหนูนะคะ มาหาหนูก่อนน้า (・`ω´・)")

        await ctx.interaction.edit_original_response(embed=info_embed("<a:MagnifierGIF:1052563354910216252> กำลังค้นหา...", f"หนูกำลังหาข้อมูล `{query}` ให้นะคะ รอแป๊บนึงน้า (・`ω´・)"))



        # ytsearch1 if not URL (faster search)
        if not query.startswith(("http://", "https://")):
            query = f"ytsearch1:{query}"

        try:
            data = await self._extract_info(query, download=False)
        except Exception as e:
            logger.error(f"yt-dlp extract error: {e}")
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "แง... หนูหาเพลงนี้ไม่เจอ หรืออาจจะโหลดไม่ได้นะคะ ขอโทษด้วยค่ะ (╥﹏╥)"))
            return

        if not data:
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "ไม่มีข้อมูลเพลงนี้เลยค่ะ (╥﹏╥)"))
            return

        entries = [data]
        is_playlist = False
        if 'entries' in data:
            entries = list(data['entries'])
            is_playlist = True

        added_count = 0
        first_track = None

        for entry in entries:
            if not entry:
                continue
            
            url = entry.get('url')
            webpage_url = entry.get('webpage_url')
            if not webpage_url and 'id' in entry:
                webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"

            title = entry.get('title', 'Unknown Title')
            duration = entry.get('duration', 0)
            thumbnail = entry.get('thumbnail', '')
            uploader = entry.get('uploader')
            if 'channel' in entry and entry['channel'] != uploader:
                uploader = f"{uploader} ({entry['channel']})" if uploader else entry['channel']
            view_count = entry.get('view_count')
            like_count = entry.get('like_count')
            comment_count = entry.get('comment_count')
            upload_date = entry.get('upload_date')
            channel_follower_count = entry.get('channel_follower_count')
            
            track = Track(
                title=title,
                duration=duration,
                thumbnail=thumbnail,
                requester=ctx.author,
                original_url=webpage_url,
                stream_url=url if not is_playlist else None,
                uploader=uploader,
                view_count=view_count,
                like_count=like_count,
                comment_count=comment_count,
                upload_date=upload_date,
                channel_follower_count=channel_follower_count
            )
            state.queue.append(track)
            if not first_track:
                first_track = track
            added_count += 1

        if added_count == 0:
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "หาเพลงไม่เจอเลยค่ะ (╥﹏╥)"))
            return

        # Update the public controller message directly
        display_track = state.current if state.current else first_track
        embed = self._build_player_embed(display_track, state)
        await self._update_controller(state, embed)
        
        # Send ephemeral confirmation to the user
        msg = f"Playlist ({added_count} เพลง)" if is_playlist else f"[{first_track.title}]({first_track.original_url})"
        await ctx.interaction.edit_original_response(embed=success_embed("✅ เพิ่มเข้าคิวแล้ว!", f"เพิ่ม {msg} ลงคิวเรียบร้อยค่ะ! ไปดูที่หน้าเล่นเพลงได้เลยนะคะ (๑>◡<๑)"))

        if not ctx.guild.voice_client:
            state.voice_client = await channel.connect()
            
        if not state.current or not state.voice_client.is_playing():
            # if playing is stopped, start it
            self.bot.loop.create_task(self._play_next_async(ctx.guild.id, auto_send=True))

    @music.command(name="pause", description="⏸️ หยุดเพลงชั่วคราว")
    async def pause(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")
        
        ctx.voice_client.pause()
        
        state = self.get_state(ctx.guild.id)
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
            
        await ctx.respond(embed=info_embed("⏸️ หยุดเพลงชั่วคราว", "หนูหยุดเพลงให้ก่อนนะคะ (・`ω´・)"))

    @music.command(name="resume", description="⏯️ เล่นเพลงต่อ")
    async def resume(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_paused():
            raise UserError("เพลงไม่ได้หยุดอยู่นะคะ", "เพลงก็เล่นอยู่ปกตินี่นา หรือไม่ได้เปิดเพลงน้า (´-ω-`)")
            
        ctx.voice_client.resume()
        
        state = self.get_state(ctx.guild.id)
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
            
        await ctx.respond(embed=info_embed("▶️ เล่นเพลงต่อ", "หนูเล่นเพลงต่อแล้วนะคะ! (๑>◡<๑)"))

    @music.command(name="stop", description="⏹️ หยุดเพลงและล้างคิวทั้งหมด")
    async def stop(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.loop_mode = "off"
        
        if state.last_controller_message:
            try:
                embeds = state.last_controller_message.embeds
                if embeds:
                    embeds[0].color = discord.Color.dark_theme()
                    await state.last_controller_message.edit(embed=embeds[0], view=None)
                else:
                    await state.last_controller_message.edit(view=None)
            except Exception:
                pass
            state.last_controller_message = None
            
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.respond(embed=success_embed("⏹️ หยุดเพลงแล้วค่ะ", "หนูหยุดเพลงและเคลียร์คิวให้หมดแล้วนะคะ (・`ω´・)"))

    @music.command(name="skip", description="⏭️ ข้ามเพลงปัจจุบัน")
    async def skip(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ ข้ามไม่ได้น้า (´・ω・)")
            
        state = self.get_state(ctx.guild.id)
        state.skip_request = True
        ctx.voice_client.stop()
        
        next_track = state.queue[0] if len(state.queue) > 0 else None
        
        if next_track:
            embed = discord.Embed(
                title=f"เพลงถัดไป: {next_track.title}",
                url=next_track.original_url,
                description="⏭️ **ข้ามเพลงให้แล้วนะคะ!** นี่คือเพลงต่อไปค่ะ",
                color=discord.Color(0x5865F2)
            )
            if next_track.thumbnail:
                embed.set_thumbnail(url=next_track.thumbnail)
        else:
            embed = discord.Embed(
                title="ข้ามเพลง",
                description="⏭️ **ข้ามเพลงให้แล้วนะคะ!** (ไม่มีเพลงในคิวแล้วค่ะ)",
                color=discord.Color(0x5865F2)
            )
        await ctx.respond(embed=embed)



    @music.command(name="nowplaying", description="🎵 ดูเพลงที่กำลังเล่นอยู่")
    async def nowplaying(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.text_channel = ctx.channel
        if not state.current:
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")

        embed = self._build_player_embed(state.current, state)
        await self._send_controls(state, ctx, embed, edit_original=False)

    @music.command(name="loop", description="🔁 ตั้งค่าการวนลูปเพลง")
    async def loop(self, ctx: discord.ApplicationContext, mode: discord.Option(str, choices=["off", "track", "queue"])):
        state = self.get_state(ctx.guild.id)
        state.loop_mode = mode
        
        if mode == "off":
            msg = "ปิดการวนลูปแล้วนะคะ (・`ω´・)"
        elif mode == "track":
            msg = "จะวนลูปเพลงนี้ไปเรื่อยๆ เลยค่ะ! (๑>◡<๑)"
        else:
            msg = "จะวนลูปทั้งคิวเลยนะคะ! (・`ω´・)"
            
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
            
        await ctx.respond(embed=success_embed("ตั้งค่าลูป", msg))

    @music.command(name="queue", description="📜 ดูคิวเพลงทั้งหมด")
    async def queue(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if not state.current and len(state.queue) == 0:
            return await ctx.respond(embed=info_embed("คิวว่าง", "ไม่มีเพลงในคิวเลยค่ะ (´・ω・)"), ephemeral=True)
            
        paginator = QueuePaginator(state, items_per_page=30)
        msg = await ctx.respond(embed=paginator.get_embed(), view=paginator)
        if isinstance(msg, discord.Interaction):
            msg = await msg.original_response()
        paginator.message = msg

    @music.command(name="volume", description="🔊 ปรับระดับเสียง (0-100)")
    async def volume(self, ctx: discord.ApplicationContext, level: discord.Option(int, min_value=0, max_value=100)):
        state = self.get_state(ctx.guild.id)
        state.volume = level / 100.0
        
        if ctx.voice_client and ctx.voice_client.source:
            if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                ctx.voice_client.source.volume = state.volume
                
        if state.current:
            embed = self._build_player_embed(state.current, state)
            await self._update_controller(state, embed)
                
        await ctx.respond(embed=success_embed("🔉 ปรับเสียง", f"ปรับเสียงเป็น {level}% แล้วนะคะ (・`ω´・)"))


def setup(bot: discord.Bot):
    bot.add_cog(PlayerCog(bot))
