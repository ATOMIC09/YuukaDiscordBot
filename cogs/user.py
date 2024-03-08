import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import pytz

class User(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")

    @commands.Cog.listener()
    async def on_ready(self):
        print("User cog loaded")

    @app_commands.command(name='user', description="👤 ดูข้อมูลของผู้ใช้")
    async def user(self, interaction: discord.Interaction, member: Optional[discord.User]):
        if member == None:
            await self.log_cog.sendlog(interaction)
        else:
            await self.log_cog.sendlog(interaction, data={'content': member})

        user = interaction.guild.get_member(interaction.user.id)
        if member != None:
            user = interaction.guild.get_member(member.id)

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
        embed.add_field(name="**สร้างบัญชีเมื่อ**", value=f'{user.created_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime("`วันที่ %d/%m/%Y` `เวลา %H:%M:%S`")}')
        embed.add_field(name="**เข้าร่วมเซิร์ฟเวอร์เมื่อ**", value=f'{user.joined_at.astimezone(tz=pytz.timezone('Asia/Bangkok')).strftime("`วันที่ %d/%m/%Y` `เวลา %H:%M:%S`")}')
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