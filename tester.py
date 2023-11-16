'''from discord.ext import commands
import discord
from discord import app_commands, ui
import os
from discord.utils import get

client = commands.Bot(command_prefix='!', intents=discord.Intents.all())

@client.command()
async def listen(ctx):
    print(ctx.guild.voice_channels)  # Print all the voice channels on the server
    channel = ctx.message.author.voice.channel
    voice_channel = get(client.voice_clients, guild=ctx.guild)
    vc = await channel.connect()
    print(vc)


Token = os.environ['YuukaTesterOldToken']
client.run(Token)


import discord
from discord.ext import commands
import os

bot = commands.Bot(command_prefix='!')

@bot.command()
async def join(ctx):
    channel = ctx.author.voice.channel
    await channel.connect()

@bot.command()
async def leave(ctx):
    voice_client = ctx.guild.voice_client
    if voice_client.is_connected():
        await voice_client.disconnect()

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel is not None:
        voice_client = await after.channel.connect()
        audio_source = discord.FFmpegPCMAudio('path/to/audio/file.mp3')
        voice_client.play(audio_source)

Token = os.environ['YuukaTesterOldToken']
bot.run(Token)
'''

import discord
from discord import app_commands, ui
from discord.ext import commands
import os

class MyClient(discord.Client):
    def __init__(self, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.setup_hook()
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------------------------------------------------')

    async def setup_hook(self):
        MY_GUILD = discord.Object(id=720687175611580426)  
        await self.tree.sync(MY_GUILD)

intents = discord.Intents.all()
intents.members = True
intents.presences = True
client = MyClient(intents=intents)

@client.tree.command(name='test')
async def test(interaction: discord.Interaction):
    await interaction.response.send_message(interaction.message.author)

@client.tree.command(name='test2')
async def test2(interaction: discord.Interaction):
    channel_total = 0
    for i in range(len(interaction.guild.text_channels)):
        if interaction.guild.text_channels[i].permissions_for(interaction.user).read_messages:
            channel_total += 1
            print(f"{interaction.user.name} has permission to read {interaction.guild.text_channels[i].name}")
        else:
            print(f"{interaction.user.name} has no permission to read {interaction.guild.text_channels[i].name}")
    print(channel_total)
    await interaction.response.send_message(f"**ตรวจพบ {channel_total} ช่อง**")

Token = os.environ['YuukaTesterOldToken']
client.run(Token)