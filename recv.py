import discord
from discord import app_commands
import voice_recv
import wave
import os

DEV_GUILD = discord.Object(id=720687175611580426)

class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=DEV_GUILD)
        await self.tree.sync(guild=DEV_GUILD)

intents = discord.Intents.default()
bot = Client(intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

def callback(member, packet):
    # Save the packet to a file
    audio_data = packet.payload
    # Convert the audio data to bytes
    audio_bytes = audio_data.to_bytes((audio_data.bit_length() + 7) // 8, byteorder='big')

    with wave.open("audio/1234.wav", "wb") as f:
        # Set the parameters of the WAV file
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(48000)

        # Write the header to the file
        f.writeframes(b'')

        # Write the audio data to the file
        f.writeframes(audio_bytes)
    packet.

    print(f"Received packet 1234")

@bot.tree.command()
async def start(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    vc = await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
    vc.listen(voice_recv.BasicSink(callback))

Token = os.environ['YuukaTesterOldToken']
bot.run(Token)