import discord
from discord.ext import commands
import asyncio
import time
from bot.logger import logger
from utils.embeds import success_embed, error_embed, info_embed, warning_embed
from utils.errors import UserError, UserWarning

class CountdisView(discord.ui.View):
    def __init__(self, target_time: int, channel: discord.VoiceChannel, author_id: int):
        super().__init__(timeout=None)
        self.target_time = target_time
        self.channel = channel
        self.author_id = author_id
        self.excepted_users: set[int] = set()
        self.task: asyncio.Task | None = None
        self.stopped = False

    @discord.ui.button(label="ยกเว้นฉัน", style=discord.ButtonStyle.primary)
    async def except_me(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id in self.excepted_users:
            self.excepted_users.remove(interaction.user.id)
            await interaction.response.send_message(f"หนูจะไม่เว้น {interaction.user.mention} แล้วนะคะ ระวังตัวด้วยล่ะ! (,,#ﾟДﾟ)", ephemeral=True)
        else:
            self.excepted_users.add(interaction.user.id)
            await interaction.response.send_message(f"รับทราบค่ะ! หนูจะเว้น {interaction.user.mention} ไว้นะคะ (๑>◡<๑)", ephemeral=True)

    # NOTE: do not name this `stop` — that would shadow View.stop()
    @discord.ui.button(label="หยุด", style=discord.ButtonStyle.danger)
    async def stop_countdown(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.stopped:
            await interaction.response.send_message("เซนเซย์คะ หนูก็หยุดนับไปแล้วไงคะ! (；￣Д￣)", ephemeral=True)
            return

        self.stopped = True
        if self.task and not self.task.done():
            self.task.cancel()

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(content=None, embed=warning_embed("ยกเลิกการนับถอยหลัง", "หยุดนับถอยหลังแล้วค่ะ! เซนเซย์เปลี่ยนใจสินะคะ (´-ω-`)"), view=self)
        self.stop()

class CountdisCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        # Track active countdowns per channel to prevent duplicates
        self.active_countdowns: set[int] = set()

    @discord.slash_command(name="countdis", description="⏰ นับถอยหลังและตัดการเชื่อมต่อ")
    async def countdis(self, ctx: discord.ApplicationContext, timer: discord.Option(int, description="เวลาเป็นหน่วยวินาที")): # type: ignore
        # Must be in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise UserError("ยังไม่ได้เข้าห้องเสียง", "เซนเซย์ต้องเข้าห้องเสียงก่อนนะคะ ถึงจะให้หนูเริ่มนับถอยหลังได้ (・`ω´・)")
        
        channel = ctx.author.voice.channel

        if timer <= 0:
            raise UserWarning("เวลาไม่ถูกต้อง", "เซนเซย์ซื้อนาฬิกาที่ไหนคะ เดี๋ยวหนูตามไปทุบ (╯°□°)╯︵ ┻━┻")
        
        if channel.id in self.active_countdowns:
            raise UserWarning("กำลังทำงานอยู่", "หนูกำลังนับถอยหลังของห้องนี้อยู่แล้วค่ะ! รอให้เสร็จก่อนนะคะเซนเซย์ (´･ω･`)?")
            
        self.active_countdowns.add(channel.id)
        
        target_timestamp = int(time.time()) + timer
        
        view = CountdisView(target_timestamp, channel, ctx.author.id)
        
        content = f"รับทราบค่ะ! เริ่มนับถอยหลังแล้วนะคะ ( • ̀ω•́ )\nเหลือเวลา: <t:{target_timestamp}:R> (ตัดการเชื่อมต่อตอน <t:{target_timestamp}:T>)\n\n*ถ้าเซนเซย์ไม่อยากถูกเตะออก กดปุ่ม `ยกเว้นฉัน` ไว้ได้เลยค่ะ!*"
        
        await ctx.respond(embed=success_embed("กำลังนับถอยหลัง...", content), view=view)
        original = await ctx.interaction.original_response()

        reply_channel = ctx.channel if isinstance(ctx.channel, discord.abc.Messageable) else None
        get_partial = getattr(reply_channel, "get_partial_message", None)
        message = get_partial(original.id) if get_partial else original

        async def countdown_task():
            try:
                # Sleep until the timer ends
                await asyncio.sleep(timer)
                
                # Time's up! Kick members
                member_count = 0
                for member in channel.members:
                    if member.voice and member.id not in view.excepted_users:
                        try:
                            await member.move_to(None)
                            member_count += 1
                        except discord.Forbidden:
                            logger.warning(f"Failed to move {member} - Missing Permissions")
                        except Exception as e:
                            logger.error(f"Error moving {member}: {e}")
                
                view.stopped = True
                for child in view.children:
                    child.disabled = True

                try:
                    await message.edit(content=None, embed=success_embed("หมดเวลา!", "เตะทุกคนออกเรียบร้อยแล้วนะคะ~ ( ≧Д≦)"), view=view)
                    view.stop()
                except discord.HTTPException as e:
                    logger.error(f"Failed to deactivate countdown embed in {channel.id}: {e}")

                if member_count > 0:
                    summary = success_embed("ดำเนินการสำเร็จ ✅", f"ตัดการเชื่อมต่อ {member_count} คน จาก <#{channel.id}> เรียบร้อยแล้วค่ะเซนเซย์! (๑•̀ㅂ•́)و✧")
                else:
                    summary = warning_embed("ว่างเปล่า...", "ไม่เห็นมีใครให้เตะออกเลยนี่คะ เซนเซย์หลอกหนูเหรอ! (,,#ﾟДﾟ)")

                try:
                    await (reply_channel.send(embed=summary) if reply_channel else ctx.send(embed=summary))
                except discord.HTTPException as e:
                    logger.error(f"Failed to send countdown summary for {channel.id}: {e}")

            except asyncio.CancelledError:
                logger.info(f"Countdown in {channel.id} was cancelled.")
            except Exception as e:
                logger.exception(f"Countdown in {channel.id} failed: {e}")
            finally:
                self.active_countdowns.discard(channel.id)

        # Start the background task and attach it to the view
        task = self.bot.loop.create_task(countdown_task())
        view.task = task

def setup(bot: discord.Bot):
    bot.add_cog(CountdisCog(bot))
