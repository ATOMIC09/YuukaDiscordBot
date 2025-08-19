import discord
from discord.ext import commands
import asyncio
import traceback
import os

class Log(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_msg = ''
        # Configure the log channel via env var if provided
        self._log_channel_id = int(os.getenv("LOG_CHANNEL_ID", "1003719893260185750"))
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Log cog loaded")

    # normal log
    async def sendlog(self, interaction, data={'content': ''}):
        print('log data:', data)
        channel = self.get_log_channel()
        sendlog = discord.Embed(title=f"**ID : **`{interaction.id}`", color=0x455EE8)
        sendlog.set_author(name=interaction.user, icon_url=interaction.user.display_avatar.url)
        sendlog.timestamp = interaction.created_at
        sendlog.add_field(name="เซิร์ฟเวอร์",value=f"`{interaction.guild}` ({interaction.guild_id})")
        sendlog.add_field(name="หมวดหมู่",value=f"`{interaction.channel.category.name}` ({interaction.channel.category.id})")
        sendlog.add_field(name="ช่อง",value=f"`{interaction.channel}` ({interaction.channel_id})")
        sendlog.add_field(name="ผู้เขียน",value=f"`{interaction.user}` ({interaction.user.id})")
        sendlog.add_field(name="คำสั่ง",value=f"```/{interaction.command.name} {data['content']}```")
        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}/{interaction.id}"))
        self.log_msg = await channel.send(embed=sendlog,view=url_view)
        await self.stillrunning(self.log_msg)
        return self.log_msg

    # error log
    async def send_error_log(self, *, interaction: discord.Interaction | None = None, error: Exception | None = None, traceback_text: str | None = None, context: dict | None = None):
        channel = self.get_log_channel()
        if traceback_text is None and error is not None:
            traceback_text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))

        embed = discord.Embed(title="❌ Error", color=0xE84545)

        if interaction is not None:
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            embed.timestamp = interaction.created_at
            try:
                embed.add_field(name="เซิร์ฟเวอร์", value=f"`{interaction.guild}` ({interaction.guild_id})", inline=False)
                embed.add_field(name="ช่อง", value=f"`{interaction.channel}` ({interaction.channel_id})", inline=False)
            except Exception:
                pass
            if getattr(interaction, 'command', None) is not None:
                embed.add_field(name="คำสั่ง", value=f"`/{interaction.command.name}`", inline=False)
            url_view = discord.ui.View()
            try:
                url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}/{interaction.id}"))
            except Exception:
                pass
        else:
            embed.set_author(name=str(self.client.user) if self.client.user else "Yuuka")

        if error is not None:
            embed.add_field(name="Exception", value=f"`{type(error).__name__}: {error}`", inline=False)

        if context:
            for k, v in context.items():
                embed.add_field(name=str(k), value=f"`{v}`", inline=True)

        if traceback_text:
            # Split large traceback into chunks that fit embed limits
            for i, segment in enumerate(self.split_text(traceback_text.replace('```', 'ˋˋˋ'), 1000)):
                embed.add_field(name="Traceback" if i == 0 else "\u200b", value=f"```py\n{segment}\n```", inline=False)

        # Send message
        try:
            if channel is None:
                raise RuntimeError("Log channel not found. Set LOG_CHANNEL_ID env var.")
            if 'url_view' in locals():
                await channel.send(embed=embed, view=url_view)
            else:
                await channel.send(embed=embed)
        except Exception as send_err:
            # Fallback to console
            print("Failed to send error log:", send_err)
            if traceback_text:
                print(traceback_text)

    def get_log_channel(self) -> discord.TextChannel | None:
        return self.client.get_channel(self._log_channel_id)
    
    async def openailog(self, interaction, data={'message': None, 'log_data': None}):
        channel = self.client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{data['message'].id}`", color=0x10a37f)
        log.set_author(name=data['message'].author, icon_url=data['message'].author.display_avatar.url)
        log.timestamp = data['message'].created_at

        prompt = data['log_data']['prompt'].replace('```', '')
        prompt_segments = self.split_text(prompt, 1000)
        for i, segment in enumerate(prompt_segments):
            log.add_field(name="Prompt" if i == 0 else "\u200b", value=f"```{segment}```")

        response = data['log_data']['response'].replace('```', '')
        response_segments = self.split_text(response, 1000)
        for i, segment in enumerate(response_segments):
            log.add_field(name="Response" if i == 0 else "\u200b", value=f"```{segment}```")

        log.add_field(name="Total Tokens", value=f"`{data['log_data']['total_tokens']}`")
        log.add_field(name="Prompt Token", value=f"`{data['log_data']['prompt_tokens']}`")
        log.add_field(name="Completion Token", value=f"`{data['log_data']['completion_tokens']}`")
        log.add_field(name="Finish Reason", value=f"`{data['log_data']['finish_reason']}`")
        log.add_field(name="Create", value=f"`{data['log_data']['created']}`")
        log.add_field(name="id", value=f"`{data['log_data']['id']}`")
        log.add_field(name="Model", value=f"`{data['log_data']['model']}`")
        log.add_field(name="Object", value=f"`{data['log_data']['object']}`")

        chat_history = data['log_data']['chat_history'].replace('```', '')
        chat_segments = self.split_text(chat_history, 1000)
        for i, segment in enumerate(chat_segments):
            log.add_field(name="Chat History" if i == 0 else "\u200b", value=f"```{segment}```")

        url_view = discord.ui.View()
        url_view.add_item(discord.ui.Button(label='Go to Message', style=discord.ButtonStyle.url, url=f"https://discord.com/channels/{data['message'].guild.id}/{data['message'].channel.id}/{data['message'].id}"))
        await channel.send(embed=log, view=url_view)

    @staticmethod
    def split_text(text, chunk_size):
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        return chunks
    
    async def stillrunning(self, log):
        await log.add_reaction("<a:AppleLoadingGIF:1052465926487953428>")

    async def runcomplete(self, emoji):
        await self.log_msg.add_reaction(emoji)
        await asyncio.sleep(1)
        await self.log_msg.remove_reaction("<a:AppleLoadingGIF:1052465926487953428>", self.client.user)


async def setup(client):
    print("Setting up Log cog")
    await client.add_cog(Log(client))