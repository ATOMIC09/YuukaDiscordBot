import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import utils.countdown as countdown

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
    @app_commands.describe(time='เวลาเป็นหน่วยวินาที')
    async def countdis(self, interaction: discord.Interaction, time: int):
        followup_sent = False
        new_message = None
        await self.log_cog.sendlog(interaction, data={'content': f'{time}'})
        try:
            all_member = interaction.user.voice.channel.members
            stop_button = discord.ui.Button(label="Stop", style=discord.ButtonStyle.red)
            exceptme_button = discord.ui.Button(label="Except Me", style=discord.ButtonStyle.primary)
            guild = interaction.guild_id
            channel = interaction.user.voice.channel
            member_count = 0

            if guild not in self.time_stop:
                self.time_stop[guild] = False
            if guild not in self.countdis_except: 
                self.countdis_except[guild] = []
            
            if time < 0:
                await interaction.response.send_message("**❌ นาฬิกาบ้านคุณช่างวิเศษเสียจริง เวลาสามารถติดลบได้**")
                await self.log_cog.runcomplete('⚠️')
            else:
                try:
                    if self.already_called[channel.id]:
                        await interaction.response.send_message("**❌ แค่ตัวเดียวก็เกินพอแล้ว**")
                        await self.log_cog.runcomplete('⚠️')
                        return
                except KeyError:
                    self.already_called[channel.id] = True
                    
                output = countdown.countdown(time)
                view = discord.ui.View()
                view.add_item(stop_button)
                view.add_item(exceptme_button)

                await interaction.response.send_message(output, view=view)
                for i in range(time):
                    await asyncio.sleep(1)
                    output = countdown.countdown(time - i - 1)
                    
                    # When stop button is clicked
                    if self.time_stop[guild] == True:
                        print(f'new_message: {new_message}')
                        if followup_sent:
                            await new_message.edit(content="**🛑 ยกเลิกการนับถอยหลังแล้ว**", view=None)
                        else:
                            await interaction.edit_original_response(content="**🛑 ยกเลิกการนับถอยหลังแล้ว**", view=None)
                        self.already_called.pop(channel.id)
                        break

                    if i <= 600: # 10 minutes before sending followup message
                        await interaction.edit_original_response(content=output)
                    else:
                        if not followup_sent:
                            # remove buttons
                            view.clear_items()
                            await interaction.edit_original_response(content="**เปลี่ยนนาฬิกาแล้ว!**", view=view)
                            # send new followup message instead
                            view.add_item(stop_button)
                            view.add_item(exceptme_button)
                            new_message = await interaction.followup.send(content=output, view=view)
                            followup_sent = True
                        else:
                            await new_message.edit(content=output)

                    # Except Me
                    async def exceptme(interaction: discord.Interaction):
                        if interaction.user.id in self.countdis_except[guild]:
                            self.countdis_except[guild].remove(interaction.user.id)
                            await interaction.response.send_message(content=f"**<@{interaction.user.id}> ไม่ถูกยกเว้นแล้ว ❌**")
                        else:
                            self.countdis_except[guild].append(interaction.user.id)
                            await interaction.response.send_message(content=f"**<@{interaction.user.id}> ถูกยกเว้นแล้ว ✅**")
                    
                    # Stop
                    async def stop(interaction: discord.Interaction):
                        self.time_stop[guild] = True
                        print('stop button clicked')

                    stop_button.callback = stop
                    exceptme_button.callback = exceptme

                if self.time_stop[guild] == False:
                    if followup_sent:
                        await new_message.edit(content="**🔔 หมดเวลา**", view=None)
                    else:
                        await interaction.edit_original_response(content="**🔔 หมดเวลา**", view=None)
                    for member in all_member:
                        if member.id in self.countdis_except[guild]:
                            continue
                        await member.move_to(None)
                        member_count += 1
                    
                    await interaction.followup.send(f"⏏️  **ตัดการเชื่อมต่อทั้ง {member_count} คน จาก `{channel}` แล้วนะ**")
                    self.already_called.pop(channel.id)

                # Reset
                self.countdis_except[guild] = []
                self.time_stop[guild] = False
                await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        
        except AttributeError:
            await interaction.response.send_message(content="**จะให้ถีบใคร? ไม่มีใครให้ถีบอะ ಠل͟ಠ**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client):
    print("Setting up Countdis cog")
    await client.add_cog(Countdis(client))