import discord
from discord.ext import commands
from discord import app_commands

class Send(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Send cog loaded")

    @app_commands.command(name='send', description="📨 ส่งข้อความด้วยบอท")
    @app_commands.describe(channel="ช่องข้อความที่จะส่ง (ID หรือ #channel)",message="ข้อความ")
    async def send(self, interaction: discord.Interaction, channel: str, *, message: str):
        # Parse channel ID from string (support both raw ID and #<id> format)
        channel_id_str = channel.strip()
        if channel_id_str.startswith('#'):
            channel_id_str = channel_id_str[1:]
        elif channel_id_str.startswith('<#') and channel_id_str.endswith('>'):
            channel_id_str = channel_id_str[2:-1]
        
        try:
            channel_id = int(channel_id_str)
            channel_obj = await self.client.fetch_channel(channel_id)
            
            if not isinstance(channel_obj, discord.TextChannel):
                embed = discord.Embed(
                    title="❌ ประเภทช่องไม่ถูกต้อง",
                    description="ช่องนี้ไม่ใช่ช่องข้อความ กรุณาเลือกช่องข้อความ",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
        except discord.NotFound:
            embed = discord.Embed(
                title="❌ ไม่พบช่องข้อความ",
                description=f"ไม่พบช่องข้อความที่มี ID: `{channel_id}`",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์เข้าถึง",
                description=f"บอทไม่มีสิทธิ์เข้าถึงช่องที่มี ID: `{channel_id}`",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        except ValueError:
            embed = discord.Embed(
                title="❌ รูปแบบไม่ถูกต้อง",
                description=f"รูปแบบ Channel ID ไม่ถูกต้อง: `{channel}`\nกรุณาใส่ไอดีช่องที่ถูกต้อง หรือใช้รูปแบบ #ชื่อช่อง",
                color=0xff0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Log after we've successfully validated the channel
        await self.log_cog.sendlog(interaction, data={'content': f'"{message}" -> {channel_obj.name} ({channel_obj.id})'})
        
        
        try:
            await interaction.response.send_message(f'"{message}" ถูกส่งไปยัง {channel_obj.mention}',ephemeral=True)
            await channel_obj.send(message)
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ ไม่มีสิทธิ์เข้าถึง",
                description=f"ไม่มีสิทธิ์ส่งข้อความในช่อง {channel_obj.mention}",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed)
            await self.log_cog.runcomplete('⚠️')
            return
        except discord.HTTPException as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"เกิดข้อผิดพลาดในการส่งข้อความ: `{e}`",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed)
            await self.log_cog.runcomplete('⚠️')
            return
            
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up Send cog")
    await client.add_cog(Send(client))