import discord
from discord.ext import commands
from discord import app_commands
from pyexcel.cookbook import merge_all_to_a_book
import pytz
import csv
import glob
from typing import Optional

class Absent(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Absent cog loaded")

    @app_commands.command(name='absent', description="🔎 หาผู้ขาดการประชุม")
    @app_commands.describe(role="ใส่บทบาทที่ต้องการหาผู้ขาดการประชุม")
    async def absent(self, interaction: discord.Interaction, role: Optional[discord.Role]):
        if role == None:
            await self.log_cog.sendlog(interaction)
        else:
            await self.log_cog.sendlog(interaction, data={'content': role})
        
        try:
            member_absent = ""
            count = 0
            vc = interaction.user.voice.channel

            data = [[f"บันทึกการขาดประชุม {vc.name}"]]
            data.append(["Number","Name","Role"])

            for member in interaction.guild.members:
                if member.voice == None:
                    if role == None:
                        member_absent += f'> {member.display_name}\n'
                        count += 1
                        data.append([count,member.display_name,"-"])
                    else:
                        if role in member.roles:
                            member_absent += f'> {member.display_name}\n'
                            count += 1
                            data.append([count,member.display_name,role.name])
            
                data.append([""])
            data.append([f"Time: {interaction.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%H:%M:%S')}"])
            data.append([f"Executed by {interaction.user.display_name}"])

            # Crate CSV file
            with open(f'temp/sheets{vc.id}_absent.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(data)

            # Create XLSX file
            merge_all_to_a_book(glob.glob(f"temp/sheets{vc.id}_absent.csv"), f"temp/sheets{vc.id}_absent.xlsx")

            # On Click Export
            get_csv = discord.ui.Button(label="Export to CSV",emoji="📤",style=discord.ButtonStyle.primary)
            get_xlsx = discord.ui.Button(label="Export to XLSX",emoji="📤",style=discord.ButtonStyle.green)

            async def get_csv_callback(interaction):
                try:
                    file = discord.File(f"temp/sheets{vc.id}_absent.csv")
                    await interaction.response.send_message(file=file)
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

            async def get_xlsx_callback(interaction):
                try:
                    file = discord.File(f"temp/sheets{vc.id}_absent.xlsx")
                    await interaction.response.send_message(file=file)
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

            get_csv.callback = get_csv_callback
            get_xlsx.callback = get_xlsx_callback
            view = discord.ui.View()
            view.add_item(get_csv)
            view.add_item(get_xlsx)

            if member_absent == "":
                member_absent = "-"

            if role == None:
                absent = discord.Embed(title="📝 บันทึกการขาดประชุม",color=0xFF3C5B)
                absent.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
                absent.add_field(name="👥 จำนวนผู้ขาด",value=f'`{count} คน`',inline=False)
                absent.add_field(name="👤 รายชื่อ", value=f'{member_absent}', inline=False)
                absent.timestamp = interaction.created_at
                await interaction.response.send_message(embed=absent,view=view)
            
            else:
                absent = discord.Embed(title="📝 บันทึกการขาดประชุม",color=0xFF3C5B)
                absent.add_field(name="🎩 บทบาท",value=f'`{role}`',inline=False)
                absent.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
                absent.add_field(name="👥 จำนวนผู้ขาด",value=f'`{count} คน`',inline=False)
                absent.add_field(name="👤 รายชื่อ", value=f'{member_absent}', inline=False)
                absent.timestamp = interaction.created_at
                await interaction.response.send_message(embed=absent,view=view)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        except:
            await interaction.response.send_message(f"**ต้องอยู่ในห้องเสียงก่อน ถึงจะหาคนขาดได้ ಠ⁠_⁠ಠ**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client: commands.Bot):
    print("Setting up Absent cog")
    await client.add_cog(Absent(client))