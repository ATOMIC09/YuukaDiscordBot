"""
bot/bot.py
Defines YuukaBot — the core bot subclass.
Responsible for: intents, event hooks, and loading all cogs automatically.
"""

from __future__ import annotations

import pkgutil
from pathlib import Path

import aiohttp
import discord

from bot.config import config
from bot.logger import _configure_logger, logger


class YuukaBot(discord.Bot):
    """
    Main bot class. Subclasses discord.Bot for application (slash) commands.
    Loads all cogs from the `cogs/` directory automatically.
    """

    def __init__(self) -> None:
        _configure_logger(config.log_level)

        intents = discord.Intents.default()
        intents.voice_states = True
        intents.message_content = True  # Required for message context menus

        # Use aiohttp's ThreadedResolver (stdlib getaddrinfo) instead of aiodns/c-ares.
        # aiodns uses the c-ares library which has known DNS failures on Windows.
        # ThreadedResolver is slightly slower but rock-solid on all platforms.
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())

        super().__init__(intents=intents, connector=connector)

    # ------------------------------------------------------------------
    # Lifecycle events
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        logger.info("Yuuka is ready! ✨")

    # ------------------------------------------------------------------
    # Cog loader
    # ------------------------------------------------------------------

    def load_cogs(self) -> None:
        """
        Recursively discovers and loads all cog modules under `cogs/`.
        Any *.py file that is not __init__.py is treated as a cog and must
        define a `setup(bot)` function.
        """
        cogs_path = Path(__file__).parent.parent / "cogs"
        self._load_cogs_from_path(cogs_path, package_prefix="cogs")

    def _load_cogs_from_path(self, path: Path, package_prefix: str) -> None:
        for finder, name, is_pkg in pkgutil.iter_modules([str(path)]):
            full_name = f"{package_prefix}.{name}"
            if is_pkg:
                # Recurse into sub-packages
                self._load_cogs_from_path(path / name, package_prefix=full_name)
            else:
                try:
                    self.load_extension(full_name)
                    logger.debug(f"Loaded cog: {full_name}")
                except Exception as exc:
                    logger.error(f"Failed to load cog {full_name}: {exc}")
