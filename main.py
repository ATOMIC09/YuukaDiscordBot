import discord
from discord.ext import commands
from discord import app_commands, ui
import os

class Yuuka(commands.Bot):
    def __init__(self, intents: discord.Intents):
        super().__init__(command_prefix="&", intents=intents)
        # self.guildinfo = {}

    async def loadcog(self):
        # At least it's O(n)
        await self.load_extension(f'cogs.log')
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and filename != 'log.py':
                await self.load_extension(f'cogs.{filename[:-3]}')

    async def on_ready(self):
        await client.loadcog()
        await self.tree.sync()
        print(f'Logged in as {self.user}')
        print('------------------------------------')

intents = discord.Intents.all()
intents.members = True
intents.presences = True
client = Yuuka(intents=intents)

Token = os.environ['YuukaTesterToken']
client.run(Token)