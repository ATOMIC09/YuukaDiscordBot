"""
main.py
Entry point for Yuuka Discord Bot.

Run with:
    uv run main.py
"""

import asyncio

from bot.bot import YuukaBot
from bot.config import config
from bot.logger import logger
from bot.patches import apply_patches
from utils.errors import setup_error_handler


async def main() -> None:
    apply_patches()  # Fix pycord 2.8.0 voice-receive regressions before connecting

    bot = YuukaBot()
    setup_error_handler(bot)
    bot.load_cogs()
    logger.info("Starting Yuuka...")
    await bot.start(config.bot_token)


if __name__ == "__main__":
    asyncio.run(main())
