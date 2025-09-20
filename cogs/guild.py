import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import pytz
import re

class Guild(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
    
    def extract_guild_id(self, guild_input: str) -> int:
        """Extract guild ID from plain ID"""
        # Remove whitespace
        guild_input = guild_input.strip()
        
        # If it's just a plain number, convert directly
        if guild_input.isdigit():
            return int(guild_input)
        
        # If none of the above, raise an error
        raise ValueError(f"Invalid guild ID format: {guild_input}")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Guild cog loaded")

    @app_commands.command(name='guild', description="🏛️ ดูข้อมูลของเซิร์ฟเวอร์")
    @app_commands.describe(guild_id="ใส่ไอดีของเซิร์ฟเวอร์")
    async def guild(self, interaction: discord.Interaction, guild_id: Optional[str]):
        if guild_id == None:
            await self.log_cog.sendlog(interaction)
        else:
            await self.log_cog.sendlog(interaction, data={'content': guild_id})

        guild = interaction.guild
        if guild_id != None:
            try:
                # Extract guild ID from plain ID
                extracted_id = self.extract_guild_id(guild_id)
                
                # First try to get from cache (if bot is a member)
                guild = self.client.get_guild(extracted_id)
                
                # If not found in cache, try to fetch basic info (works even if bot isn't a member)
                if guild is None:
                    try:
                        guild = await self.client.fetch_guild(extracted_id)
                    except discord.NotFound:
                        embed = discord.Embed(
                            title="❌ ไม่พบเซิร์ฟเวอร์", 
                            description=f"ไม่พบเซิร์ฟเวอร์ที่มี ID `{extracted_id}`\nกรุณาตรวจสอบว่าไอดีถูกต้อง",
                            color=0xff0000
                        )
                        await interaction.response.send_message(embed=embed)
                        await self.log_cog.runcomplete('❔')
                        return
                    except discord.Forbidden:
                        embed = discord.Embed(
                            title="❌ ไม่สามารถเข้าถึงได้", 
                            description=f"ไม่สามารถเข้าถึงเซิร์ฟเวอร์ ID `{extracted_id}`\nบอทอาจไม่ได้อยู่ในเซิร์ฟเวอร์นั้น หรือไม่มีสิทธิ์เข้าถึง",
                            color=0xff0000
                        )
                        await interaction.response.send_message(embed=embed)
                        await self.log_cog.runcomplete('❔')
                        return
                
                # Check if we still don't have guild info
                if guild is None:
                    embed = discord.Embed(
                        title="❌ ไม่พบเซิร์ฟเวอร์", 
                        description=f"ไม่สามารถดึงข้อมูลเซิร์ฟเวอร์ ID `{extracted_id}` ได้",
                        color=0xff0000
                    )
                    await interaction.response.send_message(embed=embed)
                    await self.log_cog.runcomplete('❔')
                    return
                    
            except ValueError as e:
                embed = discord.Embed(
                    title="❌ รูปแบบไม่ถูกต้อง", 
                    description="กรุณาใส่ไอดีของเซิร์ฟเวอร์ที่ถูกต้อง",
                    color=0xff0000
                )
                await interaction.response.send_message(embed=embed)
                await self.log_cog.runcomplete('❌')
                return

        # Guild features
        features = guild.features
        feature_names = {
            'ANIMATED_BANNER': '🎬 แบนเนอร์เคลื่อนไหว',
            'ANIMATED_ICON': '🎭 ไอคอนเคลื่อนไหว',
            'AUTO_MODERATION': '🤖 ระบบดูแลอัตโนมัติ',
            'BANNER': '🖼️ แบนเนอร์',
            'COMMUNITY': '🏘️ เซิร์ฟเวอร์ชุมชน',
            'DISCOVERABLE': '🔍 ค้นพบได้',
            'FEATURABLE': '⭐ แนะนำได้',
            'INVITES_DISABLED': '🚫 ปิดการเชิญ',
            'INVITE_SPLASH': '🌊 หน้าจอเชิญ',
            'MEMBER_VERIFICATION_GATE_ENABLED': '✅ ระบบยืนยันสมาชิก',
            'MONETIZATION_ENABLED': '💰 การทำเงิน',
            'MORE_STICKERS': '😀 สติกเกอร์เพิ่มเติม',
            'NEWS': '📰 ข่าวสาร',
            'PARTNERED': '🤝 พันธมิตร Discord',
            'PREVIEW_ENABLED': '👁️ แสดงตัวอย่าง',
            'PRIVATE_THREADS': '🔒 เธรดส่วนตัว',
            'ROLE_ICONS': '🎨 ไอคอนบทบาท',
            'TICKETED_EVENTS_ENABLED': '🎫 อีเวนต์ต้องตั๋ว',
            'VANITY_URL': '🔗 URL สั้น',
            'VERIFIED': '✅ ยืนยันแล้ว',
            'VIP_REGIONS': '🌟 เซิร์ฟเวอร์ VIP',
            'WELCOME_SCREEN_ENABLED': '👋 หน้าจอต้อนรับ',
            'SOUNDBOARD': '🔊 ซาวด์บอร์ด'
        }
        
        guild_features = [feature_names.get(feature, f'`{feature}`') for feature in features]
        features_text = '\n> '.join(guild_features) if guild_features else '`ไม่มี`'

        # Verification level
        verification_levels = {
            discord.VerificationLevel.none: "ไม่มี",
            discord.VerificationLevel.low: "ต่ำ - ต้องมีอีเมลยืนยัน",
            discord.VerificationLevel.medium: "ปานกลาง - ต้องลงทะเบียนมา 5 นาที",
            discord.VerificationLevel.high: "สูง - ต้องเป็นสมาชิกเซิร์ฟเวอร์มา 10 นาที",
            discord.VerificationLevel.highest: "สูงสุด - ต้องมีเบอร์โทรยืนยัน"
        }

        # Explicit content filter
        content_filters = {
            discord.ContentFilter.disabled: "ปิดใช้งาน",
            discord.ContentFilter.no_role: "สแกนสมาชิกที่ไม่มีบทบาท",
            discord.ContentFilter.all_members: "สแกนสมาชิกทุกคน"
        }

        # Check if we have full guild data (bot is member) or limited data (fetched)
        is_member_guild = hasattr(guild, 'members') and guild.members is not None
        
        # Get channel counts (only if bot is a member)
        if is_member_guild:
            text_channels = len([ch for ch in guild.channels if isinstance(ch, discord.TextChannel)])
            voice_channels = len([ch for ch in guild.channels if isinstance(ch, discord.VoiceChannel)])
            stage_channels = len([ch for ch in guild.channels if isinstance(ch, discord.StageChannel)])
            forum_channels = len([ch for ch in guild.channels if isinstance(ch, discord.ForumChannel)])
            categories = len([ch for ch in guild.channels if isinstance(ch, discord.CategoryChannel)])
        else:
            # Limited data - can't access channels
            text_channels = "ไม่ทราบ"
            voice_channels = "ไม่ทราบ" 
            stage_channels = 0
            forum_channels = 0
            categories = "ไม่ทราบ"

        # Get role count and breakdown (only if bot is a member)
        if is_member_guild:
            all_roles = [role for role in guild.roles if role != guild.default_role]
            role_count = len(all_roles)
            
            # Separate managed and non-managed roles
            managed_roles = [role for role in all_roles if role.managed]
            non_managed_roles = [role for role in all_roles if not role.managed]
        else:
            role_count = "ไม่ทราบ"
            managed_roles = []
            non_managed_roles = []
        
        # Get emoji and sticker counts
        emoji_count = len(guild.emojis)
        sticker_count = len(guild.stickers)

        # Get boost info and booster list (only if bot is a member)
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0
        
        if is_member_guild:
            # Get list of boosters
            boosters = []
            for member in guild.premium_subscribers:
                boosters.append(member.display_name)
            boosters_text = '\n'.join(boosters) if boosters else '`ไม่มี`'
        else:
            boosters = []
            boosters_text = '`ไม่สามารถเข้าถึงได้`'

        # Get system channels (only if bot is a member)
        system_channels = []
        if is_member_guild:
            if guild.system_channel:
                system_channels.append(f"📢 ระบบ : {guild.system_channel.mention}")
            if guild.rules_channel:
                system_channels.append(f"📜 กฎระเบียบ : {guild.rules_channel.mention}")
            if guild.public_updates_channel:
                system_channels.append(f"📰 อัปเดต : {guild.public_updates_channel.mention}")
        else:
            if guild.system_channel:
                system_channels.append(f"📢 ระบบ : #{guild.system_channel.name}")
            if guild.rules_channel:
                system_channels.append(f"📜 กฎระเบียบ : #{guild.rules_channel.name}")
            if guild.public_updates_channel:
                system_channels.append(f"📰 อัปเดต : #{guild.public_updates_channel.name}")
        
        system_channels_text = '\n'.join(system_channels) if system_channels else '`ไม่มี`'

        # Get guild limits based on boost level
        emoji_limit = 50 + (50 * boost_level)  # 50 base + 50 per level
        bitrate_limits = {0: "96", 1: "128", 2: "256", 3: "384"}
        file_size_limits = {0: "8.0", 1: "8.0", 2: "50.0", 3: "100.0"}
        
        bitrate_limit = bitrate_limits.get(boost_level, "96")
        file_size_limit = file_size_limits.get(boost_level, "8.0")

        # Calculate time since creation
        now = discord.utils.utcnow()
        time_diff = now - guild.created_at
        years = time_diff.days // 365
        months = (time_diff.days % 365) // 30
        days = (time_diff.days % 365) % 30

        # Get member statistics (only if bot is a member)
        if is_member_guild:
            online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
            bot_count = sum(1 for member in guild.members if member.bot)
            human_count = guild.member_count - bot_count
            
            # Get voice channel usage
            voice_members = sum(len(vc.members) for vc in guild.voice_channels)
            
            # Get permission overwrites count
            total_overwrites = sum(len(channel.overwrites) for channel in guild.channels)
        else:
            online_members = "ไม่ทราบ"
            bot_count = "ไม่ทราบ"
            human_count = "ไม่ทราบ"
            voice_members = 0
            total_overwrites = "ไม่ทราบ"
        
        # Get integration count (bots connected via OAuth) - only if bot is a member
        if is_member_guild:
            try:
                integrations = await guild.integrations()
                integration_count = len(integrations)
            except:
                integration_count = 0
        else:
            integration_count = "ไม่ทราบ"
        
        # Get invite count (if bot has manage_guild permission) - only if bot is a member
        if is_member_guild:
            try:
                invites = await guild.invites()
                invite_count = len(invites)
                total_invite_uses = sum(invite.uses or 0 for invite in invites)
            except:
                invite_count = "ไม่สามารถเข้าถึงได้"
                total_invite_uses = "ไม่สามารถเข้าถึงได้"
        else:
            invite_count = "ไม่ทราบ"
            total_invite_uses = "ไม่ทราบ"

        # Get member join statistics (only for smaller servers where bot is a member)
        member_ages = []
        if is_member_guild and guild.member_count <= 1000:
            for member in guild.members:
                if member.joined_at:
                    age_days = (now - member.joined_at).days
                    member_ages.append(age_days)
        
        # Get AFK information
        afk_info = f"{guild.afk_timeout//60} นาที" if guild.afk_timeout else "ไม่มี"
        afk_channel_info = f"{guild.afk_channel.mention}" if guild.afk_channel else "ไม่มี"

        # Get MFA (2FA) requirement
        mfa_required = "เปิดใช้งาน" if guild.mfa_level == discord.MFALevel.require_2fa else "ปิดใช้งาน"

        # Get default notification settings
        default_notifications = "ทุกข้อความ" if guild.default_notifications == discord.NotificationLevel.all_messages else "เฉพาะ @mentions"

        # Get NSFW level
        nsfw_levels = {
            discord.NSFWLevel.default: "ปกติ",
            discord.NSFWLevel.explicit: "มีเนื้อหา 18+",
            discord.NSFWLevel.safe: "ปลอดภัย",
            discord.NSFWLevel.age_restricted: "จำกัดอายุ"
        }
        nsfw_level = nsfw_levels.get(guild.nsfw_level, "ไม่ทราบ")

        # Get preferred locale
        preferred_locale = guild.preferred_locale or "en-US"
        locale_names = {
            "en-US": "อังกฤษ (สหรัฐ)",
            "en-GB": "อังกฤษ (สหราชอาณาจักร)", 
            "th": "ไทย",
            "ja": "ญี่ปุ่น",
            "ko": "เกาหลี",
            "zh-CN": "จีน (ประยุกต์)",
            "zh-TW": "จีน (ดั้งเดิม)"
        }
        locale_display = locale_names.get(preferred_locale, preferred_locale)

        # Get widget information
        widget_enabled = "เปิดใช้งาน" if guild.widget_enabled else "ปิดใช้งาน"
        widget_channel = guild.widget_channel.mention if guild.widget_channel else "ไม่มี"

        # Create embed
        embed = discord.Embed(title=f"ข้อมูลของเซิร์ฟเวอร์ {guild.name}", color=0x0091ff)
        
        # Set thumbnail to guild icon
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.description = f"ไอดีของเซิร์ฟเวอร์ : `{guild.id}`\nเจ้าของเซิร์ฟเวอร์ : <@{guild.owner_id}> (`{guild.owner_id}`)"

        # Format created date safely with time ago
        created_time = guild.created_at.astimezone(tz=pytz.timezone("Asia/Bangkok"))
        created_date_str = f"`วันที่ {created_time.strftime('%d/%m/%Y')}` `เวลา {created_time.strftime('%H:%M:%S')}`"
        
        # Add time ago information
        time_ago_parts = []
        if years > 0:
            time_ago_parts.append(f"{years} ปี")
        if months > 0:
            time_ago_parts.append(f"{months} เดือน")
        if days > 0:
            time_ago_parts.append(f"{days} วัน")
        
        time_ago_text = "เมื่อ " + " ".join(time_ago_parts[:2]) + "ที่แล้ว" if time_ago_parts else "วันนี้"
        
        embed.add_field(name="**สร้างเซิร์ฟเวอร์เมื่อ**", value=f"{created_date_str}\n`{time_ago_text}`")
        embed.add_field(name="**จำนวนสมาชิก**", value=f"`{guild.member_count:,} คน`")
        embed.add_field(name="**ระดับการยืนยัน**", value=f"`{verification_levels.get(guild.verification_level, 'ไม่ทราบ')}`")
        
        # Channel info
        if isinstance(text_channels, str):  # Limited data
            channel_info = f"`📝 ข้อความ: {text_channels}`\n`🔊 เสียง: {voice_channels}`\n`📁 หมวดหมู่: {categories}`"
        else:  # Full data
            channel_info = f"`📝 ข้อความ: {text_channels}`\n`🔊 เสียง: {voice_channels}`"
            if stage_channels > 0:
                channel_info += f"\n`🎭 เวที: {stage_channels}`"
            if forum_channels > 0:
                channel_info += f"\n`💬 ฟอรัม: {forum_channels}`"
            channel_info += f"\n`📁 หมวดหมู่: {categories}`"
        
        embed.add_field(name="**ช่องทั้งหมด**", value=channel_info)
        
        # Role breakdown
        if isinstance(role_count, str):  # Limited data
            role_info = f"`บทบาททั้งหมด: {role_count}`\n`- ข้อมูลเพิ่มเติม: ไม่ทราบ`"
        else:  # Full data
            role_info = f"`บทบาททั้งหมด: {role_count}`\n`- ไม่ได้จัดการอัตโนมัติ: {len(non_managed_roles)}`\n`- จัดการอัตโนมัติ: {len(managed_roles)}`"
        embed.add_field(name="**บทบาท**", value=role_info)
        
        # System channels
        embed.add_field(name="**ช่องระบบ**", value=system_channels_text)
        
        # Boost info with booster list (limit to first 10 boosters for space)
        booster_display = boosters_text
        if len(boosters) > 10:
            displayed_boosters = '\n'.join(boosters[:10])
            booster_display = f"{displayed_boosters}\n`และอีก {len(boosters) - 10} คน...`"
        
        boost_info = f"**ระดับ:** `{boost_level}/3`\n**Boost:** `{boost_count} ครั้ง`"
        if boosters:
            boost_info += f"\n**ผู้ Boost:**\n{booster_display}"
        
        embed.add_field(name="**🚀 Nitro Boost**", value=boost_info)
        
        # URL information
        url_info = ""
        if guild.icon:
            url_info += f"[ไอคอน]({guild.icon.url})\n"
        else:
            url_info += "ไอคอน : `ไม่มี`\n"
            
        if guild.banner:
            url_info += f"[แบนเนอร์]({guild.banner.url})\n"
        else:
            url_info += "แบนเนอร์ : `ไม่มี`\n"
            
        if guild.splash:
            url_info += f"[หน้าแรกเริ่ม]({guild.splash.url})\n"
        else:
            url_info += "หน้าแรกเริ่ม : `ไม่มี`\n"
            
        if guild.discovery_splash:
            url_info += f"[หน้าแรกเริ่มหน้าค้นพบ]({guild.discovery_splash.url})"
        else:
            url_info += "หน้าแรกเริ่มหน้าค้นพบ : `ไม่ปรากฏ`"
        
        embed.add_field(name="**🔗 URL**", value=url_info)
        
        # Limits
        limits_info = f"`😀 อีโมจิ: {emoji_limit}`\n`🎵 บิตเรต: {bitrate_limit}Kbps`\n`📁 ขนาดไฟล์: {file_size_limit} MB`"
        embed.add_field(name="**การจำกัด**", value=limits_info)
        
        # Emoji and stickers
        emoji_sticker_info = f"`😀 อีโมจิ: {emoji_count}/{emoji_limit}`\n`🔖 สติกเกอร์: {sticker_count}`"
        embed.add_field(name="**อีโมจิและสติกเกอร์**", value=emoji_sticker_info)
        
        embed.add_field(name="**ตัวกรองเนื้อหา**", value=f"`{content_filters.get(guild.explicit_content_filter, 'ไม่ทราบ')}`")
        
        # Member statistics
        if isinstance(human_count, str):  # Limited data
            member_stats = f"`👥 ทั้งหมด: {guild.member_count:,}`\n`👤 มนุษย์: {human_count}`\n`🤖 บอท: {bot_count}`\n`🟢 ออนไลน์: {online_members}`"
        else:  # Full data
            member_stats = f"`👥 ทั้งหมด: {guild.member_count:,}`\n`👤 มนุษย์: {human_count:,}`\n`🤖 บอท: {bot_count:,}`\n`🟢 ออนไลน์: {online_members:,}`"
            if voice_members > 0:
                member_stats += f"\n`🔊 ในห้องเสียง: {voice_members}`"
        embed.add_field(name="**สถิติสมาชิก**", value=member_stats)

        # Security & Moderation
        security_info = f"`🔐 2FA: {mfa_required}`\n`🔞 NSFW: {nsfw_level}`\n`🔔 การแจ้งเตือน: {default_notifications}`"
        embed.add_field(name="**ความปลอดภัย**", value=security_info)

        # Server Settings
        server_settings = f"`🌍 ภาษา: {locale_display}`\n`💤 AFK: {afk_info}`\n`📺 Widget: {widget_enabled}`"
        if guild.afk_channel:
            server_settings += f"\n`💤 ช่อง AFK: {afk_channel_info}`"
        if guild.widget_channel:
            server_settings += f"\n`📺 ช่อง Widget: {widget_channel}`"
        embed.add_field(name="**การตั้งค่าเซิร์ฟเวอร์**", value=server_settings)

        # Technical Information
        technical_info = f"`🔗 การเชื่อมโยง: {integration_count}`\n`🎛️ Permission Overwrites: {total_overwrites}`"
        if isinstance(invite_count, int):
            technical_info += f"\n`📨 คำเชิญ: {invite_count} ({total_invite_uses:,} ครั้ง)`"
        elif invite_count == "ไม่ทราบ":
            technical_info += f"\n`📨 คำเชิญ: {invite_count}`"
        else:
            technical_info += f"\n`📨 คำเชิญ: {invite_count}`"
        embed.add_field(name="**ข้อมูลเทคนิค**", value=technical_info)

        # Activity Statistics (if available)
        if member_ages and len(member_ages) > 0:
            avg_member_age = sum(member_ages) / len(member_ages)
            newest_member_age = min(member_ages)
            oldest_member_age = max(member_ages)
            
            activity_stats = f"`📊 อายุสมาชิกเฉลี่ย: {int(avg_member_age)} วัน`\n`🆕 สมาชิกใหม่สุด: {newest_member_age} วันที่แล้ว`\n`👴 สมาชิกเก่าสุด: {oldest_member_age} วันที่แล้ว`"
            embed.add_field(name="**สถิติกิจกรรม**", value=activity_stats)

        embed.add_field(name="**คุณสมบัติพิเศษ**", value=f"> {features_text}")
        
        # Additional metadata in footer
        embed.set_footer(text=f"Region: {guild.region if hasattr(guild, 'region') else 'Auto'} • Shard: {guild.shard_id if guild.shard_id is not None else 0}")
        
        # Set banner as image if available
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        
        embed.timestamp = interaction.created_at
        await interaction.response.send_message(embed=embed)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client):
    print("Setting up Guild cog")
    await client.add_cog(Guild(client))
