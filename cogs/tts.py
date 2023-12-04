import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import get
from gtts import gTTS

class TTS(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("TTS cog loaded")

    @app_commands.command(name='tts', description="🗣 พูดด้วยบอท")
    @app_commands.choices(language=[
    app_commands.Choice(name="🇿🇦 Afrikaans (South Africa)",value="af"),
    app_commands.Choice(name="🇩🇰 Danish (Denmark)",value="da"),
    app_commands.Choice(name="🇧🇪 Dutch (Belgium)",value="nl"),
    app_commands.Choice(name="🇺🇸 English (US)",value="en"),
    app_commands.Choice(name="🇫🇮 Finnish (Finland)",value="fi"),
    app_commands.Choice(name="🇫🇷 French (France)",value="fr"),
    app_commands.Choice(name="🇩🇪 German (Germany)",value="de"),
    app_commands.Choice(name="🇮🇳 Gujarati (India)",value="gu"),
    app_commands.Choice(name="🇮🇳 Hindi (India)",value="hi"),
    app_commands.Choice(name="🇮🇩 Indonesian (Indonesia)",value="id"),
    app_commands.Choice(name="🇮🇹 Italian (Italy)",value="it"),
    app_commands.Choice(name="🇯🇵 Japanese (Japan)",value="ja"),
    app_commands.Choice(name="🇰🇷 Korean (South Korea)",value="ko"),
    app_commands.Choice(name="🇲🇾 Malay (Malaysia)	",value="ms"),
    app_commands.Choice(name="🇧🇷 Portuguese (Brazil)",value="pt"),
    app_commands.Choice(name="🇷🇴 Romanian (Romania)",value="ro"),
    app_commands.Choice(name="🇷🇺 Russian (Russia)",value="ru"),
    app_commands.Choice(name="🇷🇸 Serbian (Serbia)",value="sr"),
    app_commands.Choice(name="🇸🇰 Slovak (Slovakia)",value="sk"),
    app_commands.Choice(name="🇪🇸 Spanish (Spain)",value="es"),
    app_commands.Choice(name="🇸🇪 Swedish (Sweden)",value="sv"),
    app_commands.Choice(name="🇹🇭 Thai (Thailand)",value="th"),
    app_commands.Choice(name="🇺🇦 Ukrainian (Ukraine)",value="uk"),
    app_commands.Choice(name="🇻🇳 Vietnamese (Vietnam)",value="vi"),
    ])
    
    @app_commands.describe(language="ภาษาของเสียงพูด",text="ข้อความ")
    async def tts(self, interaction: discord.Interaction,language: discord.app_commands.Choice[str] ,* , text: str):
        await self.log_cog.sendlog(interaction, data={'content': language.value})
        try:
            voice_channel = interaction.user.voice.channel
            voice = get(self.client.voice_clients, guild=interaction.guild)

            await interaction.response.send_message(f"<@{interaction.user.id}> : {text}")

            if voice and voice.is_connected():
                await voice.move_to(voice_channel)
            else:
                voice = await voice_channel.connect()

            tts = gTTS(text=text,lang=language.value)
            tts.save(f'temp/audio/tts_{interaction.user.id}.mp3')
            voice.play(discord.FFmpegPCMAudio(source=f'temp/audio/tts_{interaction.user.id}.mp3'))
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        except AttributeError:
            await interaction.response.send_message("❌ **ต้องอยู่ในแชทเสียงก่อน**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client: commands.Bot):
    print("Setting up TTS cog")
    await client.add_cog(TTS(client))