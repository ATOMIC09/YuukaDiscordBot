import asyncio
import collections
import dataclasses
from concurrent.futures import ThreadPoolExecutor

import discord
import yt_dlp
# Pre-import problematic module to prevent thread-unsafe circular import during yt-dlp extraction
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

class PlayerControls(discord.ui.View):
    def __init__(self, cog: "PlayerCog", state: "AudioState"):
        super().__init__(timeout=86400)  # 1 day timeout
        self.cog = cog
        self.state = state
        self.update_buttons()

    def update_buttons(self):
        if self.state.voice_client and self.state.voice_client.is_paused():
            self.pause_resume.emoji = "▶️"
            self.pause_resume.style = discord.ButtonStyle.success
        else:
            self.pause_resume.emoji = "⏸️"
            self.pause_resume.style = discord.ButtonStyle.primary
            
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
            await interaction.response.send_message("หนูไม่เห็นตัวเองในห้องเสียงเลยนะคะ (´・ω・)", ephemeral=True)
            return False
        if self.state.voice_client and interaction.user.voice.channel.id != self.state.voice_client.channel.id:
            await interaction.response.send_message("ตัวเองอยู่คนละห้องกับหนูนะคะ (・`ω´・)", ephemeral=True)
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
        await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.state.queue.clear()
        self.state.loop_mode = "off"
        self.state.last_controller_message = None
            
        if self.state.voice_client and self.state.voice_client.is_playing():
            self.state.voice_client.stop()
            
        try:
            await interaction.response.edit_message(view=None)
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

    async def _send_controls(self, state: AudioState, ctx, embed: discord.Embed, edit_original: bool = False):
        if state.last_controller_message:
            try:
                await state.last_controller_message.edit(view=None)
            except Exception:
                pass
        
        view = PlayerControls(self, state)
        
        if edit_original:
            msg = await ctx.interaction.edit_original_response(embed=embed, view=view)
            state.last_controller_message = msg
        else:
            msg = await ctx.respond(embed=embed, view=view)
            if isinstance(msg, discord.Interaction):
                try:
                    state.last_controller_message = await msg.original_response()
                except Exception:
                    pass
            else:
                state.last_controller_message = msg

    async def _extract_info(self, query: str, download: bool = False) -> dict:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            self._executor,
            lambda: ytdl.extract_info(query, download=download)
        )
        return data

    async def _play_next_async(self, guild_id: int):
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
            return

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
        except Exception as e:
            logger.error(f"Error playing track in guild {guild_id}: {e}")
            self.bot.loop.create_task(self._play_next_async(guild_id))

    music = discord.SlashCommandGroup("music", "คำสั่งสำหรับเปิดเพลง (YouTube)")

    @music.command(name="join", description="ให้หนูเข้าไปในห้องเสียงนะคะ")
    async def join(self, ctx: discord.ApplicationContext):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "ตัวเองต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        state = self.get_state(ctx.guild.id)

        if ctx.voice_client:
            if ctx.voice_client.channel.id == channel.id:
                raise UserError("หนูอยู่แล้วค่ะ", "หนูก็อยู่ในห้องนี้อยู่แล้วไงคะ (・`ω´・)")
            await ctx.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect()

        await ctx.respond(embed=success_embed("มาแล้วค่า~", f"หนูเข้ามาที่ห้อง {channel.mention} แล้วนะคะ! (๑>◡<๑)"))

    @music.command(name="leave", description="ให้หนูออกจากห้องเสียงค่ะ")
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

    @music.command(name="play", description="เปิดเพลงหรือเพิ่มเพลงเข้าคิวค่ะ (YouTube)")
    async def play(self, ctx: discord.ApplicationContext, query: discord.Option(str, "URL เพลง, Playlist หรือคำค้นหา")):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("หนูเข้าห้องไม่ได้ค่ะ", "ตัวเองต้องเข้าไปในห้องเสียงก่อนนะคะถึงจะให้หนูตามเข้าไปได้ (´・ω・)")

        channel = ctx.author.voice.channel
        state = self.get_state(ctx.guild.id)

        if ctx.voice_client:
            if ctx.voice_client.channel.id != channel.id:
                raise UserError("คนละห้องค่ะ", "ตัวเองอยู่คนละห้องกับหนูนะคะ มาหาหนูก่อนน้า (・`ω´・)")

        await ctx.respond(embed=info_embed("กำลังค้นหา...", f"หนูกำลังหาข้อมูล `{query}` ให้นะคะ รอแป๊บนึงน้า (・`ω´・)"))

        if not ctx.voice_client:
            state.voice_client = await channel.connect()

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
            
            track = Track(
                title=title,
                duration=duration,
                thumbnail=thumbnail,
                requester=ctx.author,
                original_url=webpage_url or url,
                stream_url=url if not is_playlist and url else None
            )
            state.queue.append(track)
            if not first_track:
                first_track = track
            added_count += 1

        if added_count == 0:
            await ctx.interaction.edit_original_response(embed=error_embed("หาเพลงไม่เจอค่ะ", "หาเพลงไม่เจอเลยค่ะ (╥﹏╥)"))
            return

        if is_playlist:
            embed = discord.Embed(
                title=f"Playlist ({added_count} เพลง)",
                color=discord.Color(0x2ECC71)
            )
            if first_track and first_track.thumbnail:
                embed.set_image(url=first_track.thumbnail)
            await self._send_controls(state, ctx, embed, edit_original=True)
        else:
            track = first_track
            mins, secs = divmod(track.duration, 60)
            dur_str = f"{mins}:{secs:02d}" if track.duration > 0 else "Live/Unknown"
            
            embed = discord.Embed(
                title=track.title,
                url=track.original_url,
                color=discord.Color(0x2ECC71)
            )
            embed.add_field(name="ความยาว", value=dur_str, inline=True)
            embed.add_field(name="ขอโดย", value=track.requester.mention, inline=True)
            if track.thumbnail:
                embed.set_image(url=track.thumbnail)
                
            await self._send_controls(state, ctx, embed, edit_original=True)

        if not state.current or not state.voice_client.is_playing():
            # if playing is stopped, start it
            self.bot.loop.create_task(self._play_next_async(ctx.guild.id))

    @music.command(name="pause", description="หยุดเพลงชั่วคราวค่ะ")
    async def pause(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")
        
        ctx.voice_client.pause()
        await ctx.respond(embed=info_embed("หยุดเพลงชั่วคราว", "หนูหยุดเพลงให้ก่อนนะคะ (・`ω´・)"))

    @music.command(name="resume", description="เล่นเพลงต่อค่ะ")
    async def resume(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_paused():
            raise UserError("เพลงไม่ได้หยุดอยู่นะคะ", "เพลงก็เล่นอยู่ปกตินี่นา หรือไม่ได้เปิดเพลงน้า (´-ω-`)")
            
        ctx.voice_client.resume()
        await ctx.respond(embed=info_embed("เล่นเพลงต่อ", "หนูเล่นเพลงต่อแล้วนะคะ! (๑>◡<๑)"))

    @music.command(name="stop", description="หยุดเพลงและล้างคิวทั้งหมดค่ะ")
    async def stop(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.loop_mode = "off"
        
        if state.last_controller_message:
            try:
                await state.last_controller_message.edit(view=None)
            except Exception:
                pass
            state.last_controller_message = None
            
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.respond(embed=success_embed("หยุดเพลงแล้วค่ะ", "หนูหยุดเพลงและเคลียร์คิวให้หมดแล้วนะคะ (・`ω´・)"))

    @music.command(name="skip", description="ข้ามเพลงนี้ค่ะ")
    async def skip(self, ctx: discord.ApplicationContext):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ ข้ามไม่ได้น้า (´・ω・)")
            
        state = self.get_state(ctx.guild.id)
        skipped_track = state.current
        
        state.skip_request = True
        ctx.voice_client.stop()
        
        embed = discord.Embed(
            title=skipped_track.title if skipped_track else "ข้ามเพลง",
            url=skipped_track.original_url if skipped_track else None,
            description="⏭️ **ข้ามเพลงให้แล้วนะคะ!**",
            color=discord.Color(0x5865F2)
        )
        if skipped_track and skipped_track.thumbnail:
            embed.set_image(url=skipped_track.thumbnail)
            
        await ctx.respond(embed=embed)

    @music.command(name="queue", description="ดูคิวเพลงทั้งหมดค่ะ")
    async def queue(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if len(state.queue) == 0 and not state.current:
            await ctx.respond(embed=info_embed("คิวว่างเปล่า", "ตอนนี้ไม่มีเพลงในคิวเลยค่ะ มาเพิ่มเพลงกันเถอะ! (๑>◡<๑)"))
            return

        desc = ""
        total_duration = 0
        if state.current:
            desc += f"**🎵 กำลังเล่น:** [{state.current.title}]({state.current.original_url})\n\n"
            total_duration += state.current.duration
            
        if len(state.queue) > 0:
            desc += "**🎶 คิวถัดไป:**\n"
            for i, track in enumerate(list(state.queue)):
                total_duration += track.duration
                if i < 10:
                    mins, secs = divmod(track.duration, 60)
                    desc += f"`{i+1}.` [{track.title}]({track.original_url}) `[{mins}:{secs:02d}]`\n"
                
            if len(state.queue) > 10:
                desc += f"\n*...และอีก {len(state.queue) - 10} เพลง*"

        tmins, tsecs = divmod(total_duration, 60)
        thours, tmins = divmod(tmins, 60)
        total_dur_str = f"{thours:02d}:{tmins:02d}:{tsecs:02d}" if thours > 0 else f"{tmins:02d}:{tsecs:02d}"

        embed = discord.Embed(
            title="คิวเพลงทั้งหมด",
            description=desc,
            color=discord.Color(0x5865F2)
        )
        if state.current and state.current.thumbnail:
            embed.set_image(url=state.current.thumbnail)
        embed.set_footer(text=f"วนลูป: {state.loop_mode.title()} | ระดับเสียง: {int(state.volume * 100)}% | เวลารวม: {total_dur_str}")
        await self._send_controls(state, ctx, embed, edit_original=False)

    @music.command(name="nowplaying", description="ดูเพลงที่กำลังเล่นอยู่ค่ะ")
    async def nowplaying(self, ctx: discord.ApplicationContext):
        state = self.get_state(ctx.guild.id)
        if not state.current:
            raise UserError("ไม่มีเพลงเล่นอยู่นะคะ", "ตอนนี้หนูไม่ได้เปิดเพลงอะไรอยู่เลยค่ะ (´・ω・)")

        track = state.current
        mins, secs = divmod(track.duration, 60)
        dur_str = f"{mins}:{secs:02d}" if track.duration > 0 else "Live/Unknown"
        
        embed = discord.Embed(
            title=track.title,
            url=track.original_url,
            color=discord.Color(0x5865F2)
        )
        embed.add_field(name="ความยาว", value=dur_str, inline=True)
        embed.add_field(name="ขอโดย", value=track.requester.mention, inline=True)
        if track.thumbnail:
            embed.set_image(url=track.thumbnail)
            
        await self._send_controls(state, ctx, embed, edit_original=False)

    @music.command(name="loop", description="ตั้งค่าการวนลูปเพลงค่ะ")
    async def loop(self, ctx: discord.ApplicationContext, mode: discord.Option(str, choices=["off", "track", "queue"])):
        state = self.get_state(ctx.guild.id)
        state.loop_mode = mode
        
        if mode == "off":
            msg = "ปิดการวนลูปแล้วนะคะ (・`ω´・)"
        elif mode == "track":
            msg = "จะวนลูปเพลงนี้ไปเรื่อยๆ เลยค่ะ! (๑>◡<๑)"
        else:
            msg = "จะวนลูปทั้งคิวเลยนะคะ! (・`ω´・)"
            
        await ctx.respond(embed=success_embed("ตั้งค่าลูป", msg))

    @music.command(name="volume", description="ปรับระดับเสียงค่ะ (0-100)")
    async def volume(self, ctx: discord.ApplicationContext, level: discord.Option(int, min_value=0, max_value=100)):
        state = self.get_state(ctx.guild.id)
        state.volume = level / 100.0
        
        if ctx.voice_client and ctx.voice_client.source:
            if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                ctx.voice_client.source.volume = state.volume
                
        await ctx.respond(embed=success_embed("ปรับเสียง", f"ปรับเสียงเป็น {level}% แล้วนะคะ (・`ω´・)"))


def setup(bot: discord.Bot):
    bot.add_cog(PlayerCog(bot))
