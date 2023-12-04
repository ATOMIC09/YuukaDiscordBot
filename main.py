import discord
from discord.ext import commands
import os
import shutil
from discord.ext import tasks
import psutil

class Yuuka(commands.Bot):
    def __init__(self, intents: discord.Intents):
        super().__init__(command_prefix="&", intents=intents)
        self.isAnnounce = False
        self.path_list = ['temp', 
                          'temp/ai', 
                          'temp/audio', 
                          'temp/chat', 
                          'temp/deepfry/deepfryer_input', 
                          'temp/deepfry/deepfryer_output', 
                          'temp/sheets', 
                          'temp/video']

    async def loadcog(self):
        await self.load_extension(f'cogs.log')
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and filename != 'log.py':
                await self.load_extension(f'cogs.{filename[:-3]}')

    async def create_temp_dir(self):
        for path in self.path_list:
            if not os.path.exists(path):
                print(f'+ Creating temp directory...{path}')
                os.makedirs(path)

    async def clear_temp_dir(self):
        for path in self.path_list:
            if os.path.exists(path):
                print(f'- Clearing temp directory...{path}')
                shutil.rmtree(path)

    async def on_ready(self):
        await client.loadcog()
        await client.create_temp_dir()
        resettemp.start()
        host_status_change.start()
        await self.tree.sync()
        print(f'Logged in as {self.user}')
        print('------------------------------------')

intents = discord.Intents.all()
intents.members = True
intents.presences = True
client = Yuuka(intents=intents)

@tasks.loop(hours=12)
async def resettemp():
    await client.clear_temp_dir()
    await client.create_temp_dir()

@tasks.loop(seconds=30)
async def host_status_change():
    if client.isAnnounce == False:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()[2]
        await client.change_presence(activity=discord.Game(name=f"CPU {cpu}% RAM {ram}%"))

Token = os.environ['YuukaToken']
client.run(Token)