import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import shutil
from discord.ext import tasks
import psutil
import traceback

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
                          'temp/video',
                          'temp/image',]

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

    # tree (slash) command errors
    async def on_tree_error(self, interaction: discord.Interaction, error: Exception):
        log_cog = self.get_cog("Log")
        if log_cog:
            await log_cog.send_error_log(interaction=interaction, error=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ An error occurred while executing this command.", ephemeral=True)
        except Exception:
            pass

    # prefix command errors
    async def on_command_error(self, ctx: commands.Context, error: Exception, /):
        log_cog = self.get_cog("Log")
        if log_cog:
            # Build a pseudo interaction context
            fake_interaction = getattr(ctx, 'interaction', None)
            context = {
                'Guild': f"{ctx.guild} ({getattr(ctx.guild, 'id', None)})" if ctx.guild else 'DM',
                'Channel': f"{ctx.channel} ({getattr(ctx.channel, 'id', None)})",
                'Author': f"{ctx.author} ({getattr(ctx.author, 'id', None)})",
                'Command': getattr(ctx.command, 'qualified_name', str(ctx.message.content))
            }
            await log_cog.send_error_log(interaction=fake_interaction, error=error, context=context)
        try:
            await ctx.reply("⚠️ An error occurred while executing this command.")
        except Exception:
            pass

    # generic event error hook
    async def on_error(self, event_method: str, /, *args, **kwargs):
        error_text = traceback.format_exc()
        log_cog = self.get_cog("Log")
        if log_cog:
            await log_cog.send_error_log(traceback_text=error_text, context={'Event': event_method})
        # Also print to stderr for container logs
        print(error_text)

intents = discord.Intents.all()
intents.members = True
intents.presences = True
client = Yuuka(intents=intents)

# Global error handler for slash (app) commands
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    log_cog = client.get_cog("Log")
    if log_cog:
        await log_cog.send_error_log(interaction=interaction, error=error)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("⚠️ An error occurred while executing this command.", ephemeral=True)
    except Exception:
        pass

    # Try to react with a warning sign to the original response (if possible)
    try:
        msg = await interaction.original_response()
        try:
            await msg.add_reaction('⚠️')
        except Exception:
            # Fallback: send a follow-up message and react to it
            follow = await interaction.followup.send("⚠️", wait=True)
            try:
                await follow.add_reaction('⚠️')
            except Exception:
                pass
    except Exception:
        # Last resort: try a simple follow-up
        try:
            follow = await interaction.followup.send("⚠️", wait=True)
            try:
                await follow.add_reaction('⚠️')
            except Exception:
                pass
        except Exception:
            pass

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

# attach loop error handlers to forward exceptions to Discord
@resettemp.error
async def resettemp_error_handler(error: Exception):
    log_cog = client.get_cog("Log")
    if log_cog:
        await log_cog.send_error_log(error=error, context={'Task': 'resettemp'})

@host_status_change.error
async def host_status_change_error_handler(error: Exception):
    log_cog = client.get_cog("Log")
    if log_cog:
        await log_cog.send_error_log(error=error, context={'Task': 'host_status_change'})

@client.tree.command(name="reload", description="🔄️ โหลด Cog ใหม่ทั้งหมด")
async def reload(interaction: discord.Interaction):
    try:
        await client.reload_extension(f'cogs.log')
        for filename in os.listdir('./cogs'):
                if filename.endswith('.py') and filename != 'log.py':
                        await client.reload_extension(f'cogs.{filename[:-3]}')
        await interaction.response.send_message(f"**✅ Successfully reloaded all cogs**")
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Failed! Could not reload this cog class.\n```{e}```")

load_dotenv()
Token = os.environ['YuukaToken']
client.run(Token)