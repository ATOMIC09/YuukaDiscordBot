import asyncio
import discord
from discord.ext import commands
from bot.logger import logger
from bot.config import config
from utils.embeds import COLOR_NEUTRAL, COLOR_SUCCESS, COLOR_ERROR

LOADING_EMOJI = discord.PartialEmoji(name="AppleLoadingGIF", id=1052465926487953428, animated=True)
SUCCESS_EMOJI = "✅"
REJECT_EMOJI = "❌"
ERROR_EMOJI = "⚠️"

class CommandLogCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.log_messages: dict[int, discord.Message] = {}

    def get_log_channel(self) -> discord.TextChannel | None:
        if not config.log_channel_id:
            return None
        return self.bot.get_channel(config.log_channel_id)

    def _build_log_embed(
        self, 
        ctx: discord.ApplicationContext, 
        color: discord.Color, 
        status_emoji: str,
        error_msg: str | None = None
    ) -> discord.Embed:
        user = ctx.author
        
        embed = discord.Embed(
            title=f"{status_emoji} Command Execution",
            description=f"**ID : {ctx.interaction.id}**",
            color=color,
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url if user.display_avatar else None)
        
        # Row 1
        if ctx.guild:
            embed.add_field(
                name="เซิร์ฟเวอร์",
                value=f"`{ctx.guild.name}`\n({ctx.guild.id})",
                inline=True
            )
        else:
            embed.add_field(
                name="เซิร์ฟเวอร์",
                value="`Direct Message`",
                inline=True
            )

        category = getattr(ctx.channel, "category", None)
        if category:
            embed.add_field(
                name="หมวดหมู่",
                value=f"`{category.name}`\n({category.id})",
                inline=True
            )
        else:
            embed.add_field(
                name="หมวดหมู่",
                value="`None`",
                inline=True
            )

        embed.add_field(
            name="ช่อง",
            value=f"{ctx.channel.mention if hasattr(ctx.channel, 'mention') else 'Unknown'}\n({ctx.channel_id})",
            inline=True
        )

        # Row 2
        embed.add_field(
            name="ผู้เขียน",
            value=f"{user.mention} ({user.id})",
            inline=True
        )

        command_name = f"/{ctx.command.qualified_name}" if ctx.command else "Unknown Command"
        options = []
        if ctx.interaction.data and "options" in ctx.interaction.data:
            for opt in ctx.interaction.data["options"]:
                options.append(f"{opt.get('name')}={opt.get('value', '...')}")
                
        cmd_text = command_name
        if options:
            cmd_text += "\n" + " +\n".join(options)
            
        embed.add_field(
            name="คำสั่ง",
            value=f"```\n{cmd_text}\n```",
            inline=True
        )

        if error_msg:
            embed.add_field(
                name="Error",
                value=f"```\n{error_msg}\n```",
                inline=False
            )
            
        extras = getattr(ctx.bot, "command_extras", {}).get(ctx.interaction.id)
        if extras:
            for k, v in extras.items():
                embed.add_field(name=k, value=f"`{v}`", inline=True)
                
        embed.timestamp = discord.utils.utcnow()
        return embed

    async def _get_link_view(self, ctx: discord.ApplicationContext) -> discord.ui.View | None:
        try:
            response = await ctx.interaction.original_response()
            if response and getattr(response, "jump_url", None):
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Go to Message", url=response.jump_url, style=discord.ButtonStyle.link))
                return view
        except Exception:
            pass
        return None

    async def _mark_success(self, ctx: discord.ApplicationContext, msg: discord.Message):
        view = await self._get_link_view(ctx)
            
        try:
            embed = self._build_log_embed(ctx, COLOR_SUCCESS, SUCCESS_EMOJI)
            kwargs = {"embed": embed}
            if view and not msg.components:
                kwargs["view"] = view
            await msg.edit(**kwargs)
        except Exception as e:
            logger.error(f"Failed to edit command log to success: {e}")
        finally:
            if hasattr(ctx.bot, "command_extras"):
                ctx.bot.command_extras.pop(ctx.interaction.id, None)

    async def _mark_error(self, ctx: discord.ApplicationContext, msg: discord.Message, error: discord.DiscordException):
        original_error = getattr(error, "original", error)
        is_user_error = isinstance(
            original_error, 
            (commands.CheckFailure, commands.UserInputError, commands.CommandNotFound, discord.ApplicationCommandError)
        )
        emoji_to_use = REJECT_EMOJI if is_user_error else ERROR_EMOJI
        
        view = await self._get_link_view(ctx)
        
        try:
            embed = self._build_log_embed(ctx, COLOR_ERROR, emoji_to_use, error_msg=str(original_error))
            
            kwargs = {"embed": embed}
            if view:
                kwargs["view"] = view
                
            await msg.edit(**kwargs)
        except Exception as e:
            logger.error(f"Failed to edit command log to error: {e}")
        finally:
            if hasattr(ctx.bot, "command_extras"):
                ctx.bot.command_extras.pop(ctx.interaction.id, None)

    @commands.Cog.listener()
    async def on_application_command(self, ctx: discord.ApplicationContext):
        channel = self.get_log_channel()
        if not channel:
            return
            
        state = {"msg": None, "status": "processing", "error": None}
        self.log_messages[ctx.interaction.id] = state
        
        # Wait up to 1.5 seconds for the command to send a response
        view = None
        for _ in range(15):
            await asyncio.sleep(0.1)
            view = await self._get_link_view(ctx)
            if view:
                break
                
        try:
            embed = self._build_log_embed(ctx, COLOR_NEUTRAL, str(LOADING_EMOJI))
            kwargs = {"embed": embed}
            if view:
                kwargs["view"] = view
                
            msg = await channel.send(**kwargs)
            
            state["msg"] = msg
            
            # If it finished while we were waiting, process it immediately
            if state["status"] == "completed":
                await self._mark_success(ctx, msg)
                self.log_messages.pop(ctx.interaction.id, None)
            elif state["status"] == "error":
                await self._mark_error(ctx, msg, state["error"])
                self.log_messages.pop(ctx.interaction.id, None)
                
        except Exception as e:
            logger.error(f"Failed to send command log: {e}")

    @commands.Cog.listener()
    async def on_application_command_completion(self, ctx: discord.ApplicationContext):
        state = self.log_messages.get(ctx.interaction.id)
        if not state:
            return
            
        if state["msg"] is None:
            state["status"] = "completed"
            return
            
        self.log_messages.pop(ctx.interaction.id, None)
        await self._mark_success(ctx, state["msg"])

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx: discord.ApplicationContext, error: discord.DiscordException):
        state = self.log_messages.get(ctx.interaction.id)
        if not state:
            return
            
        if state["msg"] is None:
            state["status"] = "error"
            state["error"] = error
            return
            
        self.log_messages.pop(ctx.interaction.id, None)
        await self._mark_error(ctx, state["msg"], error)

def setup(bot: discord.Bot):
    bot.add_cog(CommandLogCog(bot))
