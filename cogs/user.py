import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import pytz
import re

class User(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
    
    def extract_user_id(self, user_input: str) -> int:
        """Extract user ID from mention format or plain ID"""
        # Remove whitespace
        user_input = user_input.strip()
        
        # Check if it's a mention format <@123456> or <@!123456>
        mention_match = re.match(r'<@!?(\d+)>', user_input)
        if mention_match:
            return int(mention_match.group(1))
        
        # If it's just a plain number, convert directly
        if user_input.isdigit():
            return int(user_input)
        
        # If none of the above, raise an error
        raise ValueError(f"Invalid user ID format: {user_input}")

    @commands.Cog.listener()
    async def on_ready(self):
        print("User cog loaded")

    @app_commands.command(name='user', description="👤 ดูข้อมูลของผู้ใช้")
    @app_commands.describe(user_id="ใส่ไอดีของผู้ใช้หรือ @mention ผู้ใช้")
    async def user(self, interaction: discord.Interaction, user_id: Optional[str]):
        if user_id == None:
            await self.log_cog.sendlog(interaction)
        else:
            await self.log_cog.sendlog(interaction, data={'content': user_id})

        user = interaction.guild.get_member(interaction.user.id)
        if user_id != None:
            try:
                # Extract user ID from mention or plain ID
                extracted_id = self.extract_user_id(user_id)
                user = interaction.guild.get_member(extracted_id)
                
                # Check if user was found in the guild
                if user is None:
                    embed = discord.Embed(
                        title="❌ ไม่พบผู้ใช้", 
                        description="ไม่พบผู้ใช้ที่ระบุในเซิร์ฟเวอร์นี้",
                        color=0xff0000
                    )
                    await interaction.response.send_message(embed=embed)
                    await self.log_cog.runcomplete('❔')
                    return
                    
            except ValueError as e:
                embed = discord.Embed(
                    title="❌ รูปแบบไม่ถูกต้อง", 
                    description="กรุณาใส่ไอดีของผู้ใช้ที่ถูกต้อง หรือ @mention ผู้ใช้",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed)
                await self.log_cog.runcomplete('❌')
                return

        # Separate guilds by comma
        if user.bot == False:
            mutual_guilds = "\n> ".join([f"`{guild.name}`" for guild in user.mutual_guilds])
            len_mutual_guilds = len(user.mutual_guilds)
        else:
            mutual_guilds = "`ไม่มี`"
            len_mutual_guilds = "-"

        # Status
        status = "ออฟไลน์"
        if user.status == discord.Status.online:
            status = "<:Online:1094241869183074404> ออนไลน์"
        elif user.status == discord.Status.idle:
            status = "<:Away:1094241859418722405> ไม่อยู่"
        elif user.status == discord.Status.dnd:
            status = "<:DND:1094241861394251787> ห้ามรบกวน"
        elif user.status == discord.Status.offline:
            status = "<:Offline:1094241865773092914> ออฟไลน์"
            
        # Activity
        if user.activity != None:
            if user.activity.type == discord.ActivityType.playing:
                activity = f"`กำลังเล่น {user.activity.name}`"
            elif user.activity.type == discord.ActivityType.streaming:
                activity = f"`กำลังสตรีม {user.activity.name}`"
            elif user.activity.type == discord.ActivityType.listening:
                activity = f"`กำลังฟัง {user.activity.name}`"
            elif user.activity.type == discord.ActivityType.watching:
                activity = f"`กำลังดู {user.activity.name}`"
            elif user.activity.type == discord.ActivityType.custom:
                activity = f"`กำลังทำอะไรบางอย่าง`"
        else:
            activity = "`ไม่มีกิจกรรม`"

        # Check client status
        client_status1 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 📱 อุปกรณ์พกพา"
        client_status2 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 🖥️ เดสก์ท็อป"
        client_status3 = "<:Offline:1094241865773092914>  ออฟไลน์บน : 🌐 เว็บ"
        if user.mobile_status == discord.Status.online or user.mobile_status == discord.Status.idle or user.mobile_status == discord.Status.dnd:
            client_status1 = "<:Online:1094241869183074404>  ออนไลน์บน : 📱 อุปกรณ์พกพา"
        if user.desktop_status == discord.Status.online or user.desktop_status == discord.Status.idle or user.desktop_status == discord.Status.dnd:
            client_status2 = "<:Online:1094241869183074404>  ออนไลน์บน : 🖥️ เดสก์ท็อป"
        if user.web_status == discord.Status.online or user.web_status == discord.Status.idle or user.web_status == discord.Status.dnd:
            client_status3 = "<:Online:1094241869183074404>  ออนไลน์บน : 🌐 เว็บ"

        # Extract flags
        user_flags = user.public_flags.value
        badge_info = [
            ("<:staff:1094257629531996250>Discord Staff", discord.PublicUserFlags.staff.flag),
            ("<:icon_partneredserverowner:1094258897482690590> `Discord Partner`", discord.PublicUserFlags.partner.flag),
            ("<:Badge_HypeSquadEvents:1094259133571682507> `HypeSquad Events`", discord.PublicUserFlags.hypesquad.flag),
            ("<:discord_bughunterlv1:1094259250936696873> `Bug Hunter Level 1`", discord.PublicUserFlags.bug_hunter.flag),
            ("<:icon_hypesquadbravery:1094259446609350736> `House Bravery`", discord.PublicUserFlags.hypesquad_bravery.flag),
            ("<:icon_hypesquadbrilliance:1094259551831855204> `House Brilliance`", discord.PublicUserFlags.hypesquad_brilliance.flag),
            ("<:icon_hypesquadbalance:1094259581544312923> `House Balance`", discord.PublicUserFlags.hypesquad_balance.flag),
            ("<:Badge_EarlySupporter:1094259813472551013> `Early Supporter`", discord.PublicUserFlags.early_supporter.flag),
            ("`Team User`", discord.PublicUserFlags.team_user.flag),
            ("`System`", discord.PublicUserFlags.system.flag),
            ("<:BugHunterLvl2:1094259304212742234> `Bug Hunter Level 2`", discord.PublicUserFlags.bug_hunter_level_2.flag),
            ("`Verified Bot`", discord.PublicUserFlags.verified_bot.flag),
            ("<:Early_Verified_Bot_Developer:1094260288712355931> `Verified Bot Developer`", discord.PublicUserFlags.verified_bot_developer.flag),
            ("<:Certified_Moderator:1094260591490764962> `Discord Certified Moderator`", discord.PublicUserFlags.discord_certified_moderator.flag),
            ("`Bot HTTP Interactions`", discord.PublicUserFlags.bot_http_interactions.flag),
            ("`Spammer`", discord.PublicUserFlags.spammer.flag),
            ("<:Active_Developer_Badge:1094260754686935070> `Active Developer`", discord.PublicUserFlags.active_developer.flag),
        ]
        badges = [name for name, flag in badge_info if user_flags & flag]
        message = "\n> ".join(badges)
        if message == "":
            message = "`ไม่มี`"

        # Create embed
        embed = discord.Embed(title=f"ข้อมูลของ {user.name}", color=0x0091ff)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.description = f"ไอดีของบัญชี : `{user.id}`\nข้อมูลจากเซิร์ฟเวอร์ : `{interaction.guild.name} ({interaction.guild_id})`"
        embed.add_field(name="**ชื่อเล่น**", value=f"`{user.display_name}`")
        
        # Format created_at date safely without Thai text in strftime
        created_time = user.created_at.astimezone(tz=pytz.timezone("Asia/Bangkok"))
        created_date_str = f"`วันที่ {created_time.strftime('%d/%m/%Y')}` `เวลา {created_time.strftime('%H:%M:%S')}`"
        embed.add_field(name="**สร้างบัญชีเมื่อ**", value=created_date_str)
        
        # Format joined_at date safely without Thai text in strftime
        joined_time = user.joined_at.astimezone(tz=pytz.timezone("Asia/Bangkok"))
        joined_date_str = f"`วันที่ {joined_time.strftime('%d/%m/%Y')}` `เวลา {joined_time.strftime('%H:%M:%S')}`"
        embed.add_field(name="**เข้าร่วมเซิร์ฟเวอร์เมื่อ**", value=joined_date_str)
        
        embed.add_field(name="**กิจกรรม**", value=activity)
        embed.add_field(name=f"**เซิร์ฟเวอร์ร่วมกับบอท : {len_mutual_guilds} เซิร์ฟเวอร์**", value=f"> {mutual_guilds}")
        embed.add_field(name="**เหรียญตรา**", value=f"> {message}")
        embed.add_field(name=f"**สถานะ :  {status}**", value=f"**{client_status1}\n{client_status2}\n{client_status3}**")
        embed.timestamp = interaction.created_at
        await interaction.response.send_message(embed=embed)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client):
    print("Setting up User cog")
    await client.add_cog(User(client))