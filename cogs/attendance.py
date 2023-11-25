import discord
from discord.ext import commands
from discord import app_commands
from pyexcel.cookbook import merge_all_to_a_book
import pytz
import csv
import glob

class Attendance(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.member = ""
        self.count = 0

    @commands.Cog.listener()
    async def on_ready(self):
        print("Attendance cog loaded")

    @app_commands.command(name='attendance', description="📝 บันทึกการเข้าประชุม")
    async def attendance(self, interaction: discord.Interaction):
        await self.log_cog.sendlog(interaction)
        try:
            vc = interaction.user.voice.channel

            for user in vc.members:
                if user.bot == False:
                    self.member += f'> {user.display_name}\n'
                    self.count += 1

            log = discord.Embed(title="📝 บันทึกการเข้าประชุม",color=0x0A50C8)
            log.add_field(name="🔊 ช่องเสียง",value=f'`{vc.name}`',inline=False)
            log.add_field(name="👥 จำนวนผู้เข้าร่วม",value=f'`{self.count} คน`',inline=False)
            log.add_field(name="👤 รายชื่อ", value=f'{self.member}', inline=False)
            log.timestamp = interaction.created_at

            data = [[f"บันทึกการเข้าประชุม {vc.name}"]]
            data.append(["Number","Name","Discord Activity"])

            for i in range(self.count):
                try:
                    activity = vc.members[i].activity.name
                except:
                    activity = "-"

                data.append([i+1,vc.members[i].display_name,activity])
                
            data.append([""])
            data.append([f"Time: {interaction.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime('%H:%M:%S')}"])
            data.append([f"Executed by {interaction.user.display_name}"])

            # Create CSV file
            with open(f'temp/sheets{vc.id}_attend.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(data)

            # Create XLSX file
            merge_all_to_a_book(glob.glob(f"temp/sheets{vc.id}_attend.csv"), f"temp/sheets{vc.id}_attend.xlsx")

            # On Click Export
            get_csv = discord.ui.Button(label="Export to CSV",emoji="📤",style=discord.ButtonStyle.primary)
            get_xlsx = discord.ui.Button(label="Export to XLSX",emoji="📤",style=discord.ButtonStyle.green)

            async def get_csv_callback(interaction):
                try:
                    file = discord.File(f"temp/sheets{vc.id}_attend.csv")
                    await interaction.response.send_message(file=file)
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

            async def get_xlsx_callback(interaction):
                try:
                    file = discord.File(f"temp/sheets{vc.id}_attend.xlsx")
                    await interaction.response.send_message(file=file)
                except:
                    await interaction.response.send_message("❌ **ไฟล์หมดอายุแล้ว ต้องใช้คำสั่งใหม่อีกครั้ง**")

            get_csv.callback = get_csv_callback
            get_xlsx.callback = get_xlsx_callback
            view = discord.ui.View()
            view.add_item(get_csv)
            view.add_item(get_xlsx)
            await interaction.response.send_message(embed=log,view=view)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')
        except AttributeError:
            await interaction.response.send_message(f"**คุณต้องอยู่ในห้องเสียงก่อน ถึงจะเช็คชื่อได้ ┐⁠(⁠ ⁠˘⁠_⁠˘⁠)⁠┌**")
            await self.log_cog.runcomplete('⚠️')

async def setup(client: commands.Bot):
    print("Setting up Attendance cog")
    await client.add_cog(Attendance(client))