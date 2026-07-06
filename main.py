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
from utils.errors import setup_error_handler


async def main() -> None:
    bot = YuukaBot()
    setup_error_handler(bot)
    bot.load_cogs()
    logger.info("Starting Yuuka...")
    await bot.start(config.bot_token)


if __name__ == "__main__":
    asyncio.run(main())
