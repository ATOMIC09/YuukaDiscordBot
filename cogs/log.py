import discord
from discord.ext import commands

class Log(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_msg = ''
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Log cog loaded")

    # normal log
    async def sendlog(self, interaction, data={'content': ''}):
        print('log data:', data)
        channel = self.client.get_channel(1003719893260185750)
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
    
    async def openailog(self, interaction, data={'message': None}):
        channel = self.client.get_channel(1003719893260185750)
        log = discord.Embed(title=f"**ID : **`{data['message'].id}`", color=0x10a37f)
        log.set_author(name=data['message'].author, icon_url=data['message'].author.display_avatar.url)
        log.timestamp = data['message'].created_at

        prompt = data['context']['prompt'].replace('```', '')
        prompt_segments = data['context'].split_text(prompt, 1000)
        for i, segment in enumerate(prompt_segments):
            log.add_field(name="Prompt" if i == 0 else "\u200b", value=f"```{segment}```")

        response = data['context']['response'].replace('```', '')
        response_segments = data['context'].split_text(response, 1000)
        for i, segment in enumerate(response_segments):
            log.add_field(name="Response" if i == 0 else "\u200b", value=f"```{segment}```")

        log.add_field(name="Total Tokens", value=f"`{data['context']['total_tokens']}`")
        log.add_field(name="Prompt Token", value=f"`{data['context']['prompt_tokens']}`")
        log.add_field(name="Completion Token", value=f"`{data['context']['completion_tokens']}`")
        log.add_field(name="Finish Reason", value=f"`{data['context']['finish_reason']}`")
        log.add_field(name="Create", value=f"`{data['context']['created']}`")
        log.add_field(name="id", value=f"`{data['context']['id']}`")
        log.add_field(name="Model", value=f"`{data['context']['model']}`")
        log.add_field(name="Object", value=f"`{data['context']['object']}`")

        chat_history = data['context']['chat_history'].replace('```', '')
        chat_segments = data['context'].split_text(chat_history, 1000)
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
        await self.log_msg.remove_reaction("<a:AppleLoadingGIF:1052465926487953428>", self.client.user)


async def setup(client):
    print("Setting up Log cog")
    await client.add_cog(Log(client))