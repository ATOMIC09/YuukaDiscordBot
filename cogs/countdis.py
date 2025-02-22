import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import utils.countdown as countdown
import time

class Countdis(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.time_stop = {}
        self.countdis_except = {}
        self.already_called = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print('Countdis cog loaded')

    @app_commands.command(name="countdis", description="🔌 นับถอยหลังและตัดการเชื่อมต่อ")
    @app_commands.describe(settime='เวลาเป็นหน่วยวินาที')
    async def countdis(self, interaction: discord.Interaction, settime: int):
        await self.log_cog.sendlog(interaction, data={'content': f'{settime}'})
        try:
            all_member = interaction.user.voice.channel.members
            stop_button = discord.ui.Button(label="Stop", style=discord.ButtonStyle.red)
            exceptme_button = discord.ui.Button(label="Except Me", style=discord.ButtonStyle.primary)
            guild = interaction.guild_id
            channel = interaction.user.voice.channel
            member_count = 0
            followup_sent = False

            if guild not in self.time_stop:
                self.time_stop[guild] = False
            if guild not in self.countdis_except: 
                self.countdis_except[guild] = []
            
            if settime < 0:
                await interaction.response.send_message("**❌ นาฬิกาจินตภาพ?**")
                await self.log_cog.runcomplete('⚠️')
            else:
                try:
                    if self.already_called[channel.id]:
                        await interaction.response.send_message("**❌ แค่ตัวเดียวก็เกินพอแล้ว**")
                        await self.log_cog.runcomplete('⚠️')
                        return
                except KeyError:
                    self.already_called[channel.id] = True
                    
                start_time = int(time.time())
                end_time = start_time + settime
                output = f"⏰ เหลือเวลา <t:{end_time}:R>"

                view = discord.ui.View()
                view.add_item(stop_button)
                view.add_item(exceptme_button)

                await interaction.response.send_message(output, view=view)
                store_message = await interaction.original_response()

                # Except Me (NOT TESTED AT 15 MINS)
                async def exceptme(interaction: discord.Interaction):
                    if interaction.user.id in self.countdis_except[guild]:
                        self.countdis_except[guild].remove(interaction.user.id)
                        await interaction.response.send_message(content=f"**<@{interaction.user.id}> ไม่ถูกยกเว้นแล้ว ❌**")
                    else:
                        self.countdis_except[guild].append(interaction.user.id)
                        await interaction.response.send_message(content=f"**<@{interaction.user.id}> ถูกยกเว้นแล้ว ✅**")
            
                # Stop (NOT TESTED AT 15 MINS)
                async def stop(interaction: discord.Interaction):
                    self.time_stop[guild] = True
                    print('Stop button clicked')

                
                while int(time.time()) < end_time:
                    stop_button.callback = stop
                    exceptme_button.callback = exceptme
                    # print(f'time: {int(time.time())}')
                    # print(f'time_stop: {self.time_stop[guild]}')

                    if self.time_stop[guild]:
                        await store_message.edit(content="**🛑 ยกเลิกการนับถอยหลังแล้ว**", view=None)
                        self.already_called.pop(channel.id)
                        break
                    
                    # Update countdown when countdown is running for 10 minutes
                    if self.already_called[channel.id]:
                        if int(time.time()) <= start_time + 600:
                            if store_message:
                                await store_message.edit(content=output)
                        else:
                            if not followup_sent:
                                view.clear_items()
                                await store_message.edit(content="**เปลี่ยนนาฬิกาแล้ว!**", view=view)

                                view.add_item(stop_button)
                                view.add_item(exceptme_button)
                                store_message = await store_message.channel.send(content=output, view=view)
                                followup_sent = True
                            else:
                                await store_message.edit(content=output)
                            
                    if int(time.time()) >= end_time-1:
                        await store_message.edit(content="**🔔 หมดเวลา**", view=None)
                        for member in all_member:
                            if member.voice: 
                                if member.id in self.countdis_except[guild]:
                                    continue
                                await member.move_to(None)
                                member_count += 1
                        
                        await store_message.channel.send(f"⏏️  **ตัดการเชื่อมต่อ {member_count} คน จาก `{channel}` แล้วนะ**")
                        self.already_called.pop(channel.id)
                        break

                    await asyncio.sleep(1)

                # Reset
                self.countdis_except[guild] = []
                self.time_stop[guild] = False
                await self.log_cog.runcomplete('<:Approve:921703512382009354>')
                print('Countdown finished')

        
        except AttributeError:
            await interaction.response.send_message(content="**ไม่มีใครให้ถีบ ಠل͟ಠ**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client):
    print("Setting up Countdis cog")
    await client.add_cog(Countdis(client))