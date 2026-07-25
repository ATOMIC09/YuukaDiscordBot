import discord
from discord.ext import commands
from bot.config import config
from utils.embeds import info_embed

class HelpView(discord.ui.View):
    def __init__(self, embeds_dict: dict):
        super().__init__(timeout=180)
        self.embeds_dict = embeds_dict
        self.message = None

    @discord.ui.select(
        placeholder="ตัวเลือกเมนู",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="เครื่องมืออรรถประโยชน์", emoji="🔧", description="คำสั่งการใช้งานทั่วไป", value="util"),
            discord.SelectOption(label="จัดการรูปภาพและสื่อ", emoji="🖼️", description="ตกแต่งและรวมไฟล์สื่อ", value="media"),
            discord.SelectOption(label="ระบบเสียงและเพลง", emoji="🎵", description="บอทเปิดเพลงและฟีเจอร์เสียง", value="voice"),
            discord.SelectOption(label="จัดการห้องเสียง", emoji="🛡️", description="ระบบผู้ดูแลห้องเสียง", value="voicemod"),
            discord.SelectOption(label="ปัญญาประดิษฐ์ (AI)", emoji="🧠", description="ระบบแชทอัจฉริยะ", value="ai"),
            discord.SelectOption(label="Apps (Context Menu)", emoji="🖱️", description="เมนูคลิกขวา", value="contextmenu")
        ]
    )
    async def select_callback(self, select: discord.ui.Select, interaction: discord.Interaction):
        selected_value = select.values[0]
        
        # Update the default option so the dropdown shows the current selection
        for option in select.options:
            option.default = (option.value == selected_value)
            
        await interaction.response.edit_message(embed=self.embeds_dict[selected_value], view=self)

    async def on_timeout(self):
        # Disable all components when the view times out
        for child in self.children:
            child.disabled = True
        if hasattr(self, "message") and self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

class HelpCog(commands.Cog, name="ระบบช่วยเหลือ (Help)"):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    def _create_category_embed(self, title: str, description: str, color: int, commands_list: list) -> discord.Embed:
        embed = discord.Embed(title=f"**❔ ช่วยเหลือ**", description=f"╰ *{description}*", color=color)
        for name, value in commands_list:
            embed.add_field(name=name, value=value, inline=True)
        return embed

    @discord.slash_command(name="help", description="❓ ดูวิธีใช้งานคำสั่งทั้งหมดของบอท")
    async def help_cmd(self, ctx: discord.ApplicationContext):
        # Build command lists automatically
        util_cmds = []
        media_cmds = []
        voice_cmds = []
        voicemod_cmds = []
        ai_cmds = []
        app_cmds = []

        for cmd in self.bot.application_commands:
            cog = cmd.cog
            cog_name = cog.__cog_name__ if cog else ""
            
            # Hide owner-only commands completely from the public help menu
            if cog_name in ["AdminCog", "SendCog"]:
                continue

            if isinstance(cmd, discord.MessageCommand):
                app_cmds.append((f"{cmd.name}", f"`คลิกขวาข้อความ -> Apps`"))
                continue
            elif isinstance(cmd, discord.UserCommand):
                app_cmds.append((f"{cmd.name}", f"`คลิกขวาผู้ใช้ -> Apps`"))
                continue
                
            is_media = any(n in cog_name for n in ["Image", "ImgAudio"])
            is_voicemod = any(n in cog_name for n in ["Kick", "Countdis", "Attendance"])
            is_voice = any(n in cog_name for n in ["Voice", "Player", "Listener", "STT"]) and not is_voicemod
            is_ai = any(n in cog_name for n in ["AI", "Ai", "Chat"])
            
            if is_media:
                target_list = media_cmds
            elif is_voicemod:
                target_list = voicemod_cmds
            elif is_voice:
                target_list = voice_cmds
            elif is_ai:
                target_list = ai_cmds
            else:
                target_list = util_cmds

            if isinstance(cmd, discord.SlashCommandGroup):
                for sub in cmd.subcommands:
                    desc = sub.description or "ไม่มีคำอธิบาย"
                    target_list.append((f"{desc}", f"`/{cmd.name} {sub.name}`"))
            elif isinstance(cmd, discord.SlashCommand):
                desc = cmd.description or "ไม่มีคำอธิบาย"
                if cmd.name != "help":  # don't list help inside itself
                    target_list.append((f"{desc}", f"`/{cmd.name}`"))

        # Build Embeds
        embeds_dict = {}
        
        embeds_dict["util"] = self._create_category_embed("เครื่องมืออรรถประโยชน์", "🔧 เครื่องมืออรรถประโยชน์", 0x40eefd, util_cmds)
        embeds_dict["media"] = self._create_category_embed("จัดการรูปภาพและสื่อ", "🖼️ จัดการรูปภาพและสื่อ", 0xffd700, media_cmds)
        embeds_dict["voice"] = self._create_category_embed("ระบบเสียงและเพลง", "🎵 ระบบเสียงและเพลง", 0x1da1f2, voice_cmds)
        embeds_dict["voicemod"] = self._create_category_embed("จัดการห้องเสียง", "🛡️ จัดการห้องเสียง", 0xed4245, voicemod_cmds)
        embeds_dict["ai"] = self._create_category_embed("ปัญญาประดิษฐ์ (AI)", "🧠 ปัญญาประดิษฐ์ (AI)", 0xfb17ff, ai_cmds)
        embeds_dict["contextmenu"] = self._create_category_embed("Apps (Context Menu)", "🖱️ Apps (Context Menu)", 0x2cd453, app_cmds)

        view = HelpView(embeds_dict)
        msg = await ctx.respond(embed=embeds_dict["util"], view=view)
        
        if isinstance(msg, discord.Interaction):
            msg = await msg.original_response()
            
        view.message = msg

def setup(bot: discord.Bot):
    bot.add_cog(HelpCog(bot))
