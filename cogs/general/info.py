import discord
from discord.ext import commands
import pytz
from datetime import datetime

class InfoCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.tz = pytz.timezone("Asia/Bangkok")

    def _format_datetime(self, dt: datetime | None) -> str:
        if not dt:
            return "ไม่ทราบ"
        dt_bkk = dt.astimezone(self.tz)
        return f"`วันที่ {dt_bkk.strftime('%d/%m/%Y')}` `เวลา {dt_bkk.strftime('%H:%M:%S')}`"

    @discord.slash_command(name="user", description="👤 ดูข้อมูลผู้ใช้")
    async def userinfo(self, ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "ผู้ใช้ที่ต้องการดูข้อมูล", required=False)): # type: ignore
        await ctx.defer()
        
        target = user or ctx.author
        
        # Activity
        activity_text = "`ไม่มีกิจกรรม`"
        if target.activity:
            if target.activity.type == discord.ActivityType.playing:
                activity_text = f"`กำลังเล่น {target.activity.name}`"
            elif target.activity.type == discord.ActivityType.streaming:
                activity_text = f"`กำลังสตรีม {target.activity.name}`"
            elif target.activity.type == discord.ActivityType.listening:
                activity_text = f"`กำลังฟัง {target.activity.name}`"
            elif target.activity.type == discord.ActivityType.watching:
                activity_text = f"`กำลังดู {target.activity.name}`"
            elif target.activity.type == discord.ActivityType.custom:
                activity_text = f"`กำลังทำอะไรบางอย่าง`"

        # Check badges
        flags = target.public_flags
        badges = []
        if flags.staff: badges.append("Discord Staff")
        if flags.partner: badges.append("Partnered Server Owner")
        if flags.hypesquad: badges.append("HypeSquad Events")
        if flags.bug_hunter: badges.append("Bug Hunter Level 1")
        if flags.hypesquad_bravery: badges.append("House Bravery")
        if flags.hypesquad_brilliance: badges.append("House Brilliance")
        if flags.hypesquad_balance: badges.append("House Balance")
        if flags.early_supporter: badges.append("Early Supporter")
        if flags.bug_hunter_level_2: badges.append("Bug Hunter Level 2")
        if flags.verified_bot_developer: badges.append("Verified Bot Developer")
        if getattr(flags, "discord_certified_moderator", False): badges.append("Discord Certified Moderator")
        if getattr(flags, "active_developer", False): badges.append("Active Developer")
        if getattr(flags, "team_user", False): badges.append("Team User")
        if getattr(flags, "system", False): badges.append("System")
        if getattr(flags, "verified_bot", False): badges.append("Verified Bot")
        if getattr(flags, "bot_http_interactions", False): badges.append("Bot HTTP Interactions")
        if getattr(flags, "early_verified_bot_developer", False): badges.append("Early Verified Bot Developer")

        badge_text = "\n> ".join([f"`{b}`" for b in badges]) if badges else "`ไม่มี`"

        # Status
        status_map = {
            discord.Status.online: "🟢 ออนไลน์",
            discord.Status.idle: "🟡 ไม่อยู่",
            discord.Status.dnd: "🔴 ห้ามรบกวน",
            discord.Status.offline: "⚪ ออฟไลน์",
            discord.Status.invisible: "⚪ ออฟไลน์"
        }
        status_text = status_map.get(target.status, "⚪ ออฟไลน์")
        
        client_text = []
        if target.mobile_status != discord.Status.offline:
            client_text.append("📱 มือถือ")
        if target.desktop_status != discord.Status.offline:
            client_text.append("🖥️ เดสก์ท็อป")
        if target.web_status != discord.Status.offline:
            client_text.append("🌐 เว็บ")
            
        client_str = " | ".join(client_text) if client_text else "ออฟไลน์ทั้งหมด"
        
        # Roles
        roles = [r.mention for r in reversed(target.roles[1:])]
        if len(roles) > 10:
            role_text = " ".join(roles[:10]) + f" และอีก {len(roles)-10} ยศ"
        elif roles:
            role_text = " ".join(roles)
        else:
            role_text = "`ไม่มียศ`"

        embed = discord.Embed(title=f"ข้อมูลของ {target.name}", color=0x0091ff)
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)
            
        embed.description = f"ไอดีของบัญชี: `{target.id}`\nข้อมูลจากเซิร์ฟเวอร์: `{ctx.guild.name}`"
        embed.add_field(name="**ชื่อเล่น**", value=f"`{target.display_name}`", inline=False)
        embed.add_field(name="**สถานะ**", value=f"{status_text} ({client_str})", inline=False)
        embed.add_field(name="**สร้างบัญชีเมื่อ**", value=self._format_datetime(target.created_at), inline=False)
        embed.add_field(name="**เข้าร่วมเซิร์ฟเวอร์เมื่อ**", value=self._format_datetime(target.joined_at), inline=False)
        
        # New: Booster status & Timeout status
        if target.premium_since:
            embed.add_field(name="**🚀 บูสต์เซิร์ฟเวอร์เมื่อ**", value=self._format_datetime(target.premium_since), inline=False)
            
        if target.timed_out and target.communication_disabled_until:
            embed.add_field(name="**🔇 ถูกระงับการใช้งานถึง**", value=self._format_datetime(target.communication_disabled_until), inline=False)
            
        embed.add_field(name="**ยศทั้งหมด**", value=role_text, inline=False)
        embed.add_field(name="**กิจกรรม**", value=activity_text, inline=False)
        embed.add_field(name="**เหรียญตรา**", value=f"> {badge_text}", inline=False)
        
        embed.set_footer(text="ประมวลผลข้อมูลเรียบร้อยค่ะ! ( • ̀ω•́ )")
        embed.timestamp = discord.utils.utcnow()
        
        await ctx.respond(embed=embed)

    @discord.slash_command(name="server", description="🏢 ดูข้อมูลของเซิร์ฟเวอร์นี้")
    async def serverinfo(self, ctx: discord.ApplicationContext):
        guild = ctx.guild
        await ctx.defer()

        # Guild features - Enhanced with comprehensive list from DiscordLists repository
        features = guild.features
        feature_names = {
            # Core Features
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
            'SOUNDBOARD': '🔊 ซาวด์บอร์ด',
            
            # Activities & Voice Features
            'ACTIVITIES_ALPHA': '🎮 กิจกรรมช่องเสียง (อัลฟ่า)',
            'ACTIVITIES_EMPLOYEE': '🏢 กิจกรรมช่องเสียง (พนักงาน)',
            'ACTIVITIES_INTERNAL_DEV': '🔧 กิจกรรมช่องเสียง (พัฒนา)',
            'ACTIVITY_FEED_DISABLED_BY_USER': '📰 ปิดฟีดกิจกรรม',
            'ACTIVITY_FEED_ENABLED_BY_USER': '📰 เปิดฟีดกิจกรรม',
            'EXPOSED_TO_ACTIVITIES_WTP_EXPERIMENT': '🧪 ทดลองกิจกรรม',
            'HAD_EARLY_ACTIVITIES_ACCESS': '🎯 เข้าถึงกิจกรรมก่อน',
            
            # Audio & Video Quality
            'AUDIO_BITRATE_128_KBPS': '🔊 เสียง 128Kbps',
            'AUDIO_BITRATE_256_KBPS': '🔊 เสียง 256Kbps',
            'AUDIO_BITRATE_384_KBPS': '🔊 เสียง 384Kbps',
            'VIDEO_BITRATE_ENHANCED': '📹 วิดีโอคุณภาพสูง',
            'VIDEO_QUALITY_720_60FPS': '📹 วิดีโอ 720p 60fps',
            'VIDEO_QUALITY_1080_60FPS': '📹 วิดีโอ 1080p 60fps',
            'VOICE_CHANNEL_EFFECTS': '🎭 เอฟเฟกต์ช่องเสียง',
            'VOICE_IN_THREADS': '🔊 เสียงในเธรด',
            
            # AutoMod Features
            'AUTOMOD_TRIGGER_KEYWORD_FILTER': '🛡️ กรองคำหยาบ',
            'AUTOMOD_TRIGGER_ML_SPAM_FILTER': '🤖 กรองสแปม AI',
            'AUTOMOD_TRIGGER_SPAM_LINK_FILTER': '🔗 กรองลิงก์สแปม',
            'AUTOMOD_TRIGGER_USER_PROFILE': '👤 ตรวจโปรไฟล์',
            'GUILD_AUTOMOD_DEFAULT_LIST': '📋 รายการออโต้มอดเริ่มต้น',
            
            # Boost Features
            'BOOSTING_TIERS_EXPERIMENT_MEDIUM_GUILD': '🚀 ทดลอง Boost (กลาง)',
            'BOOSTING_TIERS_EXPERIMENT_SMALL_GUILD': '🚀 ทดลอง Boost (เล็ก)',
            'EXPOSED_TO_BOOSTING_TIERS_EXPERIMENT': '🚀 ทดลอง Boost',
            'PREMIUM_TIER_3_OVERRIDE': '💎 Boost ระดับ 3 บังคับ',
            'TIERLESS_BOOSTING': '🆙 Boost ไร้ระดับ',
            'TIERLESS_BOOSTING_CLIENT_TEST': '🧪 ทดลอง Boost ไร้ระดับ',
            'TIERLESS_BOOSTING_SYSTEM_MESSAGE': '💬 ข้อความระบบ Boost',
            'TIERLESS_BOOSTING_TEST': '🧪 ทดสอบ Boost ไร้ระดับ',
            
            # Channel Features
            'CHANNEL_BANNER': '🖼️ แบนเนอร์ช่อง',
            'CHANNEL_EMOJIS_GENERATED': '😀 อีโมจิช่องสร้างอัตโนมัติ',
            'CHANNEL_HIGHLIGHTS': '⭐ ไฮไลท์ช่อง',
            'CHANNEL_HIGHLIGHTS_DISABLED': '⭐ ปิดไฮไลท์ช่อง',
            'CHANNEL_ICON_EMOJIS_GENERATED': '🎯 ไอคอนช่องสร้างอัตโนมัติ',
            'THREADS_ENABLED': '🧵 เปิดใช้เธรด',
            'THREE_DAY_THREAD_ARCHIVE': '📦 เก็บเธรด 3 วัน',
            'SEVEN_DAY_THREAD_ARCHIVE': '📦 เก็บเธรด 7 วัน',
            'NEW_THREAD_PERMISSIONS': '🔐 สิทธิ์เธรดใหม่',
            'INCREASED_THREAD_LIMIT': '🔢 เพิ่มลิมิตเธรด',
            
            # Community Features
            'COMMUNITY_CANARY': '🐦 ชุมชนทดลอง',
            'COMMUNITY_EXP_LARGE_GATED': '🚪 ชุมชนใหญ่มีการกั้น',
            'COMMUNITY_EXP_LARGE_UNGATED': '🌐 ชุมชนใหญ่ไม่กั้น',
            'COMMUNITY_EXP_MEDIUM': '🏘️ ชุมชนขนาดกลาง',
            'NON_COMMUNITY_RAID_ALERTS': '🚨 แจ้งเตือนบุกรุกไม่ใช่ชุมชน',
            'RAID_ALERTS_DISABLED': '🚫 ปิดแจ้งเตือนบุกรุก',
            'RAID_ALERTS_ENABLED': '🚨 เปิดแจ้งเตือนบุกรุก',
            'RESTRICT_SPAM_RISK_GUILDS': '🛡️ จำกัดความเสี่ยงสแปม',
            
            # Creator & Monetization
            'CREATOR_ACCEPTED_NEW_TERMS': '✅ ยอมรับเงื่อนไขใหม่',
            'CREATOR_MONETIZABLE': '💰 สร้างรายได้ได้',
            'CREATOR_MONETIZABLE_DISABLED': '🚫 ปิดการสร้างรายได้',
            'CREATOR_MONETIZABLE_PENDING_NEW_OWNER_ONBOARDING': '⏳ รอเจ้าของใหม่',
            'CREATOR_MONETIZABLE_PROVISIONAL': '⚠️ การสร้างรายได้ชั่วคราว',
            'CREATOR_MONETIZABLE_RESTRICTED': '🔒 การสร้างรายได้ถูกจำกัด',
            'CREATOR_MONETIZABLE_WHITEGLOVE': '🤝 การสร้างรายได้พิเศษ',
            'CREATOR_STORE_PAGE': '🏪 หน้าร้านค้าผู้สร้าง',
            'ROLE_SUBSCRIPTIONS_AVAILABLE_FOR_PURCHASE': '💰 สมัครบทบาทได้',
            'ROLE_SUBSCRIPTIONS_ENABLED': '💳 เปิดสมัครบทบาท',
            'ROLE_SUBSCRIPTIONS_ENABLED_FOR_PURCHASE': '🛒 เปิดซื้อบทบาท',
            
            # Developer Features
            'BOT_DEVELOPER_EARLY_ACCESS': '🤖 เข้าถึงก่อนนักพัฒนาบอท',
            'DEVELOPER_SUPPORT_SERVER': '💻 เซิร์ฟเวอร์สนับสนุนนักพัฒนา',
            
            # Discovery Features
            'DISCOVERABLE_DISABLED': '🚫 ปิดการค้นพบถาวร',
            'ENABLED_DISCOVERABLE_BEFORE': '📜 เคยเปิดการค้นพบ',
            
            # File & Storage
            'MAX_FILE_SIZE_50_MB': '📁 ไฟล์ 50MB',
            'MAX_FILE_SIZE_100_MB': '📁 ไฟล์ 100MB',
            
            # Guild Management
            'FORWARDING_DISABLED': '🚫 ปิดการส่งต่อ',
            'GUILD_COMMUNICATION_DISABLED_GUILDS': '🔇 ปิดการสื่อสาร',
            'GUILD_HOME_OVERRIDE': '🏠 หน้าหลักพิเศษ',
            'GUILD_MEMBER_VERIFICATION_EXPERIMENT': '🧪 ทดลองยืนยันสมาชิก',
            'GUILD_ONBOARDING': '🎯 ระบบแนะนำ',
            'GUILD_ONBOARDING_ADMIN_ONLY': '👑 แนะนำเฉพาะแอดมิน',
            'GUILD_ONBOARDING_EVER_ENABLED': '📜 เคยเปิดระบบแนะนำ',
            'GUILD_ONBOARDING_HAS_PROMPTS': '💬 มีคำถามแนะนำ',
            'GUILD_ROLE_SUBSCRIPTIONS': '💳 สมัครบทบาทเซิร์ฟเวอร์',
            'GUILD_SERVER_GUIDE': '📖 คู่มือเซิร์ฟเวอร์',
            'GUILD_TAGS': '🏷️ แท็กเซิร์ฟเวอร์',
            'GUILD_WEB_PAGE_VANITY_URL': '🌐 URL หน้าเว็บ',
            
            # Hub Features
            'HUB': '🎓 ศูนย์กลางนักเรียน',
            'LINKED_TO_HUB': '🔗 เชื่อมกับศูนย์กลาง',
            'HAS_DIRECTORY_ENTRY': '📂 มีรายการไดเรกทอรี',
            
            # Member Features
            'MEMBER_LIST_DISABLED': '👥 ปิดรายชื่อสมาชิก',
            'MEMBER_PROFILES': '👤 โปรไฟล์สมาชิก',
            'MEMBER_SAFETY_PAGE_ROLLOUT': '🛡️ หน้าความปลอดภัยสมาชิก',
            'MEMBER_VERIFICATION_MANUAL_APPROVAL': '✋ อนุมัติสมาชิกแบบแมนนวล',
            'MEMBER_VERIFICATION_ROLLOUT_TEST': '🧪 ทดสอบยืนยันสมาชิก',
            'ENABLED_MODERATION_EXPERIENCE_FOR_NON_COMMUNITY': '🛡️ ประสบการณ์ดูแลไม่ใช่ชุมชน',
            
            # More Features
            'MORE_EMOJI': '😀 อีโมจิเพิ่มเติม',
            'MORE_SOUNDBOARD': '🔊 ซาวด์บอร์ดเพิ่มเติม',
            
            # Product Features
            'GUILD_PRODUCTS': '🛍️ ผลิตภัณฑ์เซิร์ฟเวอร์',
            'GUILD_PRODUCTS_ALLOW_ARCHIVED_FILE': '📦 อนุญาตไฟล์บีบอัด',
            'PRODUCTS_AVAILABLE_FOR_PURCHASE': '🛒 ผลิตภัณฑ์ซื้อได้',
            
            # Special Features
            'BURST_REACTIONS': '💥 รีแอคชั่นระเบิด',
            'ENHANCED_ROLE_COLORS': '🎨 สีบทบาทขั้นสูง',
            'GUESTS_ENABLED': '👥 เปิดใช้แขก',
            'INTERNAL_EMPLOYEE_ONLY': '🏢 พนักงานเท่านั้น',
            'LURKABLE': '👀 ดูได้โดยไม่เข้าร่วม',
            'MOBILE_WEB_ROLE_SUBSCRIPTION_PURCHASE_PAGE': '📱 หน้าซื้อบทบาทมือถือ',
            'TEXT_IN_STAGE_ENABLED': '📝 ข้อความในเวที',
            'STAGE_CHANNEL_VIEWERS_50': '👥 ผู้ชมเวที 50 คน',
            'STAGE_CHANNEL_VIEWERS_150': '👥 ผู้ชมเวที 150 คน',
            'STAGE_CHANNEL_VIEWERS_300': '👥 ผู้ชมเวที 300 คน',
            
            # Testing & Experimental
            'AGE_VERIFICATION_LARGE_GUILD': '🔞 ยืนยันอายุเซิร์ฟเวอร์ใหญ่',
            'BFG': '🔥 เซิร์ฟเวอร์พิเศษขนาดใหญ่',
            'GENERATED_TEST_GUILD': '🧪 เซิร์ฟเวอร์ทดสอบ',
            'HIDE_FROM_EXPERIMENT_UI': '🫥 ซ่อนจาก UI ทดลอง',
            'RAPIDASH_TEST': '⚡ ทดสอบ Rapidash',
            'RAPIDASH_TEST_REBIRTH': '🔄 ทดสอบ Rapidash ใหม่',
            'SHARD': '⚡ เชิร์ด',
            'RELAY_ENABLED': '🔄 เปิดรีเลย์',
            'FORCE_RELAY': '🔄 บังคับรีเลย์',
            
            # Game-Specific Features
            'GENSHIN_L30': '⚔️ Genshin Impact L30',
            'VALORANT_L30': '🎯 Valorant L30',
            
            # Deprecated Features (still showing for info)
            'APPLICATION_COMMAND_PERMISSIONS_V2': '⚙️ สิทธิ์คำสั่งแอปฯ v2',
            'CLAN': '⚔️ กิลด์',
            'CLAN_DISCOVERY_DISABLED': '🚫 ปิดค้นพบกิลด์',
            'COMMERCE': '🛒 พาณิชย์',
            'PUBLIC': '🌐 สาธารณะ (เก่า)',
            'PUBLIC_DISABLED': '🚫 ปิดสาธารณะ (เก่า)',
            
            # Summary Features  
            'SUMMARIES_DISABLED': '📋 ปิดสรุป',
            'SUMMARIES_ENABLED': '📋 เปิดสรุป',
            'SUMMARIES_DISABLED_BY_USER': '🚫 ผู้ใช้ปิดสรุป',
            'SUMMARIES_ENABLED_BY_USER': '✅ ผู้ใช้เปิดสรุป',
            
            # Other Features
            'LEADERBOARD_ENABLED': '🏆 เปิดลีดเดอร์บอร์ด',
            'MARKETPLACES_CONNECTION_ROLES': '🛒 บทบาทเชื่อมตลาด',
            'REPORT_TO_MOD_PILOT': '📢 รายงานถึงมอดไพลอต',
            'REPORT_TO_MOD_SURVEY': '📊 สำรวจรายงานมอด',
            'SERVER_PROFILES_TEST': '👤 ทดสอบโปรไฟล์เซิร์ฟเวอร์'
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
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            stage_channels = len(guild.stage_channels)
            forum_channels = len(guild.forum_channels)
            categories = len(guild.categories)
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
                system_channels.append(f"📢 ระบบ: {guild.system_channel.mention}")
            if guild.rules_channel:
                system_channels.append(f"📜 กฎระเบียบ: {guild.rules_channel.mention}")
            if guild.public_updates_channel:
                system_channels.append(f"📰 อัปเดต: {guild.public_updates_channel.mention}")
        else:
            if guild.system_channel:
                system_channels.append(f"📢 ระบบ: #{guild.system_channel.name}")
            if guild.rules_channel:
                system_channels.append(f"📜 กฎระเบียบ: #{guild.rules_channel.name}")
            if guild.public_updates_channel:
                system_channels.append(f"📰 อัปเดต: #{guild.public_updates_channel.name}")
        
        system_channels_text = '\n'.join(system_channels) if system_channels else '`ไม่มี`'

        # Get comprehensive guild limits
        emoji_limit = guild.emoji_limit
        sticker_limit = guild.sticker_limit
        soundboard_limit = getattr(guild, 'soundboard_limit', 8)
        audio_bitrate_limit = f"{guild.bitrate_limit // 1000}kbps"
        file_size_limit = f"{guild.filesize_limit // (1024 * 1024)}MB"
        
        # Video quality limits
        stream_quality_limits = {0: "720p@30fps", 1: "720p@60fps", 2: "720p@60fps", 3: "720p@60fps"}
        go_live_quality_limits = {0: "720p@60fps", 1: "720p@60fps", 2: "1080p@60fps", 3: "1080p@60fps"}
        stream_quality = stream_quality_limits.get(boost_level, "720p@30fps")
        go_live_quality = go_live_quality_limits.get(boost_level, "720p@60fps")
        
        # Video stage seats limits
        video_stage_limit = getattr(guild, 'max_video_channel_users', 50)
        
        # Maximum concurrent activities based on boost level
        concurrent_activities_limits = {0: 2, 1: 3, 2: 5, 3: "ไม่จำกัด"}
        concurrent_activities_limit = concurrent_activities_limits.get(boost_level, 2)
        
        max_members_formatted = f"{guild.max_members:,}" if getattr(guild, 'max_members', None) else "25,000,000"
        
        # Universal Discord limits (applies to all servers regardless of boost level)
        universal_limits = {
            'max_members': max_members_formatted,
            'max_categories': '50',
            'max_channels': '500',
            'max_channels_per_category': '50',
            'max_roles': '250',
            'max_invites': '999',
            'audit_log_retention': '45 วัน',
            'max_followed_channels': '10 ต่อช่อง',
            'max_thread_members': '1,000',
            'max_thread_role_mentions': '10',
            'video_channel_members': '25',
            'stage_channel_viewers': '10,000'
        }

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
        mfa_required = "เปิดใช้งาน" if guild.mfa_level == 1 else "ปิดใช้งาน"

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
        try:
            w = await guild.widget()
            widget_enabled = "เปิดใช้งาน" if w.enabled else "ปิดใช้งาน"
            widget_channel = w.channel.mention if w.channel else "ไม่มี"
        except:
            widget_enabled = "ปิดใช้งาน"
            widget_channel = "ไม่มี"

        # Create embed
        embed = discord.Embed(title=f"ข้อมูลของเซิร์ฟเวอร์ {guild.name}", color=0x0091ff)
        
        # Set thumbnail to guild icon
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.description = f"ไอดีของเซิร์ฟเวอร์: `{guild.id}`\nเจ้าของเซิร์ฟเวอร์: <@{guild.owner_id}> `({guild.owner_id})`"

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
            channel_info = f"📝 ข้อความ: `{text_channels}`\n🔊 เสียง: `{voice_channels}`\n📁 หมวดหมู่: `{categories}`"
        else:  # Full data
            channel_info = f"📝 ข้อความ: `{text_channels}`\n🔊 เสียง: `{voice_channels}`"
            if stage_channels > 0:
                channel_info += f"\n🎭 เวที: `{stage_channels}`"
            if forum_channels > 0:
                channel_info += f"\n💬 ฟอรัม: `{forum_channels}`"
            channel_info += f"\n📁 หมวดหมู่: `{categories}`"
        
        embed.add_field(name="**ช่องทั้งหมด**", value=channel_info)
        
        # Role breakdown
        if isinstance(role_count, str):  # Limited data
            role_info = f"บทบาททั้งหมด: `{role_count}`\n- ข้อมูลเพิ่มเติม: `ไม่ทราบ`"
        else:  # Full data
            role_info = f"บทบาททั้งหมด: `{role_count}`\n- ไม่ได้จัดการอัตโนมัติ: `{len(non_managed_roles)}`\n- จัดการอัตโนมัติ: `{len(managed_roles)}`"
        embed.add_field(name="**บทบาท**", value=role_info)
        
        # System channels
        embed.add_field(name="**ช่องระบบ**", value=system_channels_text)
        
        # Boost info with booster list (limit to first 10 boosters for space)
        booster_display = boosters_text
        if len(boosters) > 10:
            displayed_boosters = '\n'.join(boosters[:10])
            booster_display = f"{displayed_boosters}\n`และอีก {len(boosters) - 10} คน...`"
        
        boost_info = f"ระดับ: `{boost_level}/3`\nBoost: `{boost_count} ครั้ง`"
        if boosters:
            boost_info += f"\nผู้ Boost:\n{booster_display}"
        
        embed.add_field(name="**🚀 Nitro Boost**", value=boost_info)
        
        # URL information
        url_info = ""
        if guild.icon:
            url_info += f"ไอคอน: [ดูไอคอน]({guild.icon.url})\n"
        else:
            url_info += "ไอคอน: `ไม่มี`\n"
            
        if guild.banner:
            url_info += f"แบนเนอร์: [ดูแบนเนอร์]({guild.banner.url})\n"
        else:
            url_info += "แบนเนอร์: `ไม่มี`\n"
            
        if guild.splash:
            url_info += f"หน้าแรกเริ่ม: [ดูหน้าแรกเริ่ม]({guild.splash.url})\n"
        else:
            url_info += "หน้าแรกเริ่ม: `ไม่มี`\n"
            
        if guild.discovery_splash:
            url_info += f"หน้าแรกเริ่มหน้าค้นพบ: [ดูหน้าแรกเริ่ม]({guild.discovery_splash.url})"
        else:
            url_info += "หน้าแรกเริ่มหน้าค้นพบ: `ไม่ปรากฏ`"
        
        embed.add_field(name="**🔗 URL**", value=url_info)
        
        # Enhanced Server Limits & Boost Benefits
        limits_info = f"😀 อีโมจิ: `{emoji_limit} สล็อต`\n🔖 สติกเกอร์: `{sticker_limit} สล็อต`\n🔊 ซาวด์บอร์ด: `{soundboard_limit} สล็อต`\n🎵 เสียง: `{audio_bitrate_limit}`\n📁 อัปโหลด: `{file_size_limit}`\n📹 สตรีม: `{stream_quality}`\n🎥 Go Live: `{go_live_quality}`"
        embed.add_field(name="**🚀 ขีดจำกัดตาม Boost**", value=limits_info)
        
        # Universal Discord Limits
        universal_info = f"👥 สมาชิกสูงสุด: `{universal_limits['max_members']}`\n📁 หมวดหมู่: `{universal_limits['max_categories']}`\n#️⃣ ช่องทั้งหมด: `{universal_limits['max_channels']}`\n🎭 บทบาท: `{universal_limits['max_roles']}`\n📨 คำเชิญ: `{universal_limits['max_invites']}`\n📊 Audit Log: `{universal_limits['audit_log_retention']}`"
        embed.add_field(name="**📋 ขีดจำกัดสากล**", value=universal_info)
        
        # Advanced Limits & Features  
        advanced_info = f"🧵 เธรดสมาชิก: `{universal_limits['max_thread_members']}`\n🎭 ที่เธรด: `{universal_limits['max_thread_role_mentions']} บทบาท`\n📹 วิดีโอช่อง: `{universal_limits['video_channel_members']}`\n🎭 เวทีผู้ชม: `{universal_limits['stage_channel_viewers']}`\n🎬 เวทีวิดีโอ: `{video_stage_limit} ที่นั่ง`\n🎮 กิจกรรมพร้อมกัน: `{concurrent_activities_limit}`"
        embed.add_field(name="**⚙️ ขีดจำกัดขั้นสูง**", value=advanced_info)
        
        # Current Usage vs Limits
        emoji_sticker_info = f"😀 อีโมจิ: `{emoji_count}/{emoji_limit}`\n🔖 สติกเกอร์: `{sticker_count}/{sticker_limit}`"
        embed.add_field(name="**📊 การใช้งานปัจจุบัน**", value=emoji_sticker_info)
        
        embed.add_field(name="**ตัวกรองเนื้อหา**", value=f"`{content_filters.get(guild.explicit_content_filter, 'ไม่ทราบ')}`")
        
        # Member statistics
        if isinstance(human_count, str):  # Limited data
            member_stats = f"👥 ทั้งหมด: `{guild.member_count:,}`\n👤 มนุษย์: `{human_count}`\n🤖 บอท: `{bot_count}`\n🟢 ออนไลน์: `{online_members}`"
        else:  # Full data
            member_stats = f"👥 ทั้งหมด: `{guild.member_count:,}`\n👤 มนุษย์: `{human_count:,}`\n🤖 บอท: `{bot_count:,}`\n🟢 ออนไลน์: `{online_members:,}`"
            if voice_members > 0:
                member_stats += f"\n🔊 ในห้องเสียง: `{voice_members}`"
        embed.add_field(name="**สถิติสมาชิก**", value=member_stats)

        # Security & Moderation
        security_info = f"🔐 2FA: `{mfa_required}`\n🔞 NSFW: `{nsfw_level}`\n🔔 การแจ้งเตือน: `{default_notifications}`"
        embed.add_field(name="**ความปลอดภัย**", value=security_info)

        # Server Settings
        server_settings = f"🌍 ภาษา: `{locale_display}`\n💤 AFK: `{afk_info}`\n📺 Widget: `{widget_enabled}`"
        if guild.afk_channel:
            server_settings += f"\n💤 ช่อง AFK: {afk_channel_info}"
        if widget_channel != "ไม่มี":
            server_settings += f"\n📺 ช่อง Widget: {widget_channel}"
        embed.add_field(name="**การตั้งค่าเซิร์ฟเวอร์**", value=server_settings)

        # Technical Information
        technical_info = f"🔗 การเชื่อมโยง: `{integration_count}`\n🎛️ Permission Overwrites: `{total_overwrites}`"
        if isinstance(invite_count, int):
            technical_info += f"\n📨 คำเชิญ: `{invite_count} ({total_invite_uses:,} ครั้ง)`"
        elif invite_count == "ไม่ทราบ":
            technical_info += f"\n📨 คำเชิญ: `{invite_count}`"
        else:
            technical_info += f"\n📨 คำเชิญ: `{invite_count}`"
        embed.add_field(name="**ข้อมูลเทคนิค**", value=technical_info)

        # Activity Statistics (if available)
        if member_ages and len(member_ages) > 0:
            avg_member_age = sum(member_ages) / len(member_ages)
            newest_member_age = min(member_ages)
            oldest_member_age = max(member_ages)
            
            activity_stats = f"📊 อายุสมาชิกเฉลี่ย: `{int(avg_member_age)} วัน`\n🆕 สมาชิกใหม่สุด: `{newest_member_age} วันที่แล้ว`\n👴 สมาชิกเก่าสุด: `{oldest_member_age} วันที่แล้ว`"
            embed.add_field(name="**สถิติกิจกรรม**", value=activity_stats)

        # Boost Level Details & Benefits
        boost_descriptions = {
            0: "⚪ ไม่มี Boost - คุณสมบัติพื้นฐาน",
            1: "🔷 Level 1 - ไอคอนเคลื่อนไหว, เสียงคุณภาพดี",
            2: "🔶 Level 2 - แบนเนอร์, อัปโหลด 50MB, บทบาทไอคอน",
            3: "💎 Level 3 - URL สั้น, แบนเนอร์เคลื่อนไหว, อัปโหลด 100MB"
        }
        boost_description = boost_descriptions.get(boost_level, "❓ ไม่ทราบ")
        
        # Check for special community program status
        special_status = []
        if 'PARTNERED' in features:
            special_status.append("🤝 Discord Partner")
        if 'VERIFIED' in features:
            special_status.append("✅ Verified Server")
        if 'DISCOVERABLE' in features:
            special_status.append("🔍 Public Discovery")
        if 'COMMUNITY' in features:
            special_status.append("🏘️ Community Server")
        if 'HUB' in features:
            special_status.append("🎓 Student Hub")
        if 'DEVELOPER_SUPPORT_SERVER' in features:
            special_status.append("💻 Developer Support")
        
        special_status_text = '\n'.join(special_status) if special_status else '`ไม่มีสถานะพิเศษ`'
        
        boost_info_detailed = f"ระดับ: `{boost_description}`\nBoost: `{boost_count} ครั้ง`"
        if special_status:
            boost_info_detailed += f"\nสถานะพิเศษ:\n{special_status_text}"
        
        embed.add_field(name="**🚀 ข้อมูล Boost & สถานะ**", value=boost_info_detailed)

        # Enhanced Features Display
        # Categorize features for better readability
        feature_categories = {
            'core': [],
            'boost': [],
            'community': [],
            'experimental': [],
            'special': []
        }
        
        # Categorize features
        for feature in features:
            feature_name = feature_names.get(feature, f'`{feature}`')
            if feature in ['ANIMATED_ICON', 'ANIMATED_BANNER', 'BANNER', 'VANITY_URL', 'ROLE_ICONS']:
                feature_categories['boost'].append(feature_name)
            elif feature in ['COMMUNITY', 'DISCOVERABLE', 'PARTNERED', 'VERIFIED', 'NEWS', 'HUB']:
                feature_categories['community'].append(feature_name)
            elif feature in ['AUTO_MODERATION', 'MEMBER_VERIFICATION_GATE_ENABLED', 'WELCOME_SCREEN_ENABLED', 'PRIVATE_THREADS']:
                feature_categories['core'].append(feature_name)
            elif 'TEST' in feature or 'EXPERIMENT' in feature or 'ALPHA' in feature or 'BETA' in feature:
                feature_categories['experimental'].append(feature_name)
            else:
                feature_categories['special'].append(feature_name)
        
        # Build categorized features text
        categorized_features = []
        if feature_categories['community']:
            categorized_features.append(f"**🏘️ ชุมชน & การยืนยัน:**\n> " + '\n> '.join(feature_categories['community'][:8]))
        if feature_categories['boost']:
            categorized_features.append(f"**🚀 คุณสมบัติ Boost:**\n> " + '\n> '.join(feature_categories['boost'][:6]))
        if feature_categories['core']:
            categorized_features.append(f"**⚙️ หลัก & ความปลอดภัย:**\n> " + '\n> '.join(feature_categories['core'][:6]))
        if feature_categories['special']:
            categorized_features.append(f"**✨ พิเศษ & อื่นๆ:**\n> " + '\n> '.join(feature_categories['special'][:6]))
        if feature_categories['experimental']:
            categorized_features.append(f"**🧪 ทดลอง & ทดสอบ:**\n> " + '\n> '.join(feature_categories['experimental'][:4]))
        
        features_display = '\n\n'.join(categorized_features) if categorized_features else '`ไม่มีคุณสมบัติพิเศษ`'
        
        embed.add_field(name="🌟 คุณสมบัติของเซิร์ฟเวอร์", value=features_display, inline=False)
        
        # Enhanced metadata in footer with comprehensive information
        footer_text = f"API Version: v{discord.__version__}"
        if hasattr(guild, 'region'):
            footer_text += f" • Region: {guild.region}"
        else:
            footer_text += " • Region: Auto"
        if guild.shard_id is not None:
            footer_text += f" • Shard: {guild.shard_id}"
        footer_text += f" • Features: {len(features)} รายการ"
        if boost_count > 0:
            footer_text += f" • Boosters: {len(boosters)} คน"
        
        embed.set_footer(text=footer_text)
        
        # Add comprehensive info about Discord limits in footer note
        if boost_level == 3:
            embed.add_field(
                name="📌 หมายเหตุสำคัญ", 
                value=f"เซิร์ฟเวอร์นี้มี Boost ระดับสูงสุด! คุณสมบัติพิเศษ: `URL สั้น`, `อัปโหลด 100MB`, `เสียง 384kbps`, `วิดีโอ 1080p@60fps`, และ `อีโมจิ 250 สล็อต`\nข้อมูลจาก `DiscordLists repository`", 
                inline=False
            )
        
        # Set banner as image if available
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        
        embed.timestamp = discord.utils.utcnow()
        await ctx.respond(embed=embed)


def setup(bot: discord.Bot):
    bot.add_cog(InfoCog(bot))
