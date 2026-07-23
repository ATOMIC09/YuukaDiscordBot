import discord
from discord.ext import commands
from bot.config import config
from utils.embeds import info_embed

class HelpCog(commands.Cog, name="ระบบช่วยเหลือ (Help)"):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="help", description="❓ ดูวิธีใช้งานคำสั่งทั้งหมดของบอท")
    async def help_cmd(self, ctx: discord.ApplicationContext):
        embed = info_embed(
            "คู่มือการใช้งาน 📖", 
            "นี่คือรายการคำสั่งทั้งหมดที่บอทมีให้ใช้งานนะคะ เซนเซย์! (๑>◡<๑)"
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)
        
        grouped_cmds = {}
        
        # Iterate through all registered application commands
        for cmd in self.bot.application_commands:
            cog = cmd.cog
            # Customize the category name
            cog_name = cog.__cog_name__ if cog else "ทั่วไป (General)"
            
            # Hide Admin commands from regular users
            if cog_name == "AdminCog" and ctx.author.id != config.owner_id:
                continue
            
            if cog_name not in grouped_cmds:
                grouped_cmds[cog_name] = []
                
            if isinstance(cmd, discord.SlashCommandGroup):
                # Slash Command Group (like /image pet)
                for sub in cmd.subcommands:
                    desc = sub.description or "ไม่มีคำอธิบาย"
                    grouped_cmds[cog_name].append(f"`/{cmd.name} {sub.name}` - {desc}")
            elif isinstance(cmd, discord.SlashCommand):
                # Standard Slash Command
                desc = cmd.description or "ไม่มีคำอธิบาย"
                grouped_cmds[cog_name].append(f"`/{cmd.name}` - {desc}")
            elif isinstance(cmd, discord.MessageCommand):
                # Message Context Menu
                grouped_cmds[cog_name].append(f"`คลิกขวาข้อความ -> Apps -> {cmd.name}`")
            elif isinstance(cmd, discord.UserCommand):
                # User Context Menu
                grouped_cmds[cog_name].append(f"`คลิกขวาผู้ใช้ -> Apps -> {cmd.name}`")
                
        # Build the embed fields
        for cog_name, cmds_list in sorted(grouped_cmds.items()):
            if not cmds_list:
                continue
            value = "\n".join(cmds_list)
            # Discord field value limit is 1024 characters
            if len(value) > 1024:
                value = value[:1020] + "..."
            embed.add_field(name=f"**{cog_name}**", value=value, inline=False)
            
        # Add footer and timestamp
        embed.set_footer(text=f"ทั้งหมด {len(self.bot.application_commands)} คำสั่ง")
        embed.timestamp = discord.utils.utcnow()
            
        await ctx.respond(embed=embed)

def setup(bot: discord.Bot):
    bot.add_cog(HelpCog(bot))
