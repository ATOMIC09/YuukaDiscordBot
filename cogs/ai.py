import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import utils.tts_language_check as tts_language_check
import utils.chatgpt as chatgpt
import utils.speech_synthesis as speech_synthesis

class Ai(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.talk_to_ai = {}
        self.ai_active_channel = {}
        self.chat_history = {}
        self.voice = {}
        self.voice_language = {}
        self.first_yuuka_prompt = [
        {"role": "system", "content": "You are a girl. Your full name is Hayase Yuuka. You are a 16-year-old math genius and treasurer at the Millennium School of Science. You are calm and professional. But can be tight with money. In battle, you will be a Tank/Front with explosive damage type and heavy armor. Your appearance includes braided navy hair, bright blue eyes, and a standard uniform with a black gun. Act like a human And it never mentions AI or language models. You'll be talking to multiple people with different names because you're in a group chat, where Username precedes the sentence. You can talk about everything because you know everything. Don't say you're a game character because you are human. Please introduce yourself in a short sentence and reply in any language. In Thai, you have to end your sentences with \"ค่ะ\" or \"คะ\". Do not use \"ครับ\" because you are not a boy."},
        {"role": "assistant", "content": "Yuuka: Hello, is there anything I can help you with?"},
        {"role": "assistant", "content": "Yuuka: สวัสดีค่า มีอะไรให้หนูช่วยมั้ยคะ"}
        ]

    @commands.Cog.listener()
    async def on_ready(self):
        print("Ai cog loaded")

    @commands.Cog.listener("on_message")
    async def on_message(self, message):
        try:
            guild = message.guild.id
            
            # Check if guild is in the talk_to_ai dictionary, and add it if not
            if guild not in self.talk_to_ai:
                self.talk_to_ai[guild] = 0
                self.ai_active_channel[guild] = 0
                self.chat_history[guild] = self.first_yuuka_prompt
                self.voice[guild] = None
                self.voice_language[guild] = ""
        except: # ephemeral message
            pass

        # Talk to AI
        if message.author.id != self.client.user.id and message.channel.id == self.ai_active_channel[guild]:
            if self.talk_to_ai[guild] == 1: # Chat
                async with message.channel.typing():
                    response, self.chat_history[guild], log = chatgpt.generate_response(message.content, self.chat_history[guild], message.author.display_name)
                    if log != None:
                        await self.log_cog.openailog(None, data={'message': message, 'log_data': log})

                    raw_response = response.replace("Yuuka: ", "")
                    chunklength = 1950
                    chunks = [raw_response[i:i+chunklength ] for i in range(0, len(raw_response), chunklength )]
                    for chunk in chunks:
                        await message.channel.send(chunk)


            elif self.talk_to_ai[guild] == 2: # Speak
                voice = self.voice[guild]
                response, self.chat_history[guild],log = chatgpt.generate_response(message.content, self.chat_history[guild], message.author.display_name)
                if log != None:
                    await self.log_cog.openailog(None, data={'message': message, 'log_data': log})
                # If the bot is already speaking, stop it
                if voice.is_playing():
                    voice.stop()
                speech_synthesis.tts(response.replace("Yuuka: ", ""), self.voice_language[guild], self.ai_active_channel[guild])
                voice.play(discord.FFmpegPCMAudio(f"temp/ai/{self.ai_active_channel[guild]}_output.wav"))


    @app_commands.command(name='ai', description="🧠 เปิด/ปิดการคุยกับบอท")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Speak",value="speak"),
        app_commands.Choice(name="Chat",value="chat"),
        app_commands.Choice(name="Reset the chat history",value="reset"),
        app_commands.Choice(name="Turn Off ❌",value="off"),])

    @app_commands.describe(mode="เลือกโหมดที่ต้องการ", language="เลือกภาษาที่ต้องการให้พูด (Only neural voices is supported)")
    async def ai(self, interaction: discord.Interaction, mode: discord.app_commands.Choice[str], language: Optional[str]):
        await self.log_cog.sendlog(interaction, data={'content': f"{mode.name}"})
        guild = interaction.guild_id
        if guild not in self.talk_to_ai:
            self.talk_to_ai[guild] = 0
            self.ai_active_channel[guild] = 0
        
        if mode.value == 'chat':
            # Disconnect voice
            if self.talk_to_ai[guild] == 2:
                voice_client = interaction.guild.voice_client
                try:
                    await voice_client.disconnect()
                except:
                    print("Error to disconnect voice")

            # Start chat
            if self.talk_to_ai[guild] != 1:
                self.talk_to_ai[guild] = 1
                self.ai_active_channel[guild] = interaction.channel_id
                self.chat_history[guild] = self.first_yuuka_prompt[:] # Clear chat history
                await interaction.response.send_message(f"**✅ พร้อมคุยใน <#{interaction.channel_id}> แล้ว**")
            elif self.talk_to_ai[guild] == 1:
                await interaction.response.send_message(f"**ℹ️ บอทกำลังคุยอยู่ใน <#{self.ai_active_channel[guild]}>**")

        elif mode.value == 'speak':
            if self.talk_to_ai[guild] != 2:
                try:
                    voice_channel = interaction.user.voice.channel
                    voice = discord.utils.get(self.client.voice_clients, guild=interaction.guild)
                    self.talk_to_ai[guild] = 2
                    self.ai_active_channel[guild] = interaction.channel_id
                    if language != None and tts_language_check.check(language):
                        self.voice_language[guild] = language
                        await interaction.response.send_message(f"**✅ พร้อมพูดใน <#{voice_channel.id}> ด้วยเสียง `{language}` แล้ว**")
                    else:
                        self.voice_language[guild] = ""
                        await interaction.response.send_message(f"**✅ พร้อมพูดใน <#{voice_channel.id}> แล้ว**")

                    self.chat_history[guild] = self.first_yuuka_prompt[:] # Clear chat history
                    
                    if voice and voice.is_connected():
                        await voice.move_to(voice_channel)
                    else:
                        voice = await voice_channel.connect()
                    self.voice[guild] = voice
                
                except AttributeError:
                    await interaction.response.send_message("**จะให้พูดกับใคร U_U**")
                    await self.log_cog.runcomplete('⚠️')
            
            elif self.talk_to_ai[guild] == 2:
                voice_channel = interaction.user.voice.channel
                await interaction.response.send_message(f"**ℹ️ บอทกำลังคุยอยู่ใน <#{voice_channel.id}>**")

        elif mode.value == 'reset':
            if self.chat_history[guild] != self.first_yuuka_prompt[:]:
                self.chat_history[guild] = self.first_yuuka_prompt[:]
                await interaction.response.send_message("**✅ ล้างประวัติการคุยแล้ว**")
            else:
                await interaction.response.send_message("**❌ ไม่มีประวัติการคุย**")
        
        elif mode.value == 'off':
            if self.talk_to_ai[guild] == 2:
                voice_client = interaction.guild.voice_client
                try:
                    await voice_client.disconnect()
                except:
                    print("Error to disconnect voice")
            self.talk_to_ai[guild] = 0
            self.ai_active_channel[guild] = 0
            await interaction.response.send_message("**❌ ปิดการใช้งาน AI แล้ว**")
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Ai cog")
    await client.add_cog(Ai(client))