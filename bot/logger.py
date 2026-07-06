"""
bot/logger.py
Configures the shared loguru logger for the entire project.
All modules should import `logger` from here:

    from bot.logger import logger
"""

import sys

from loguru import logger as _logger

# Import config lazily to avoid circular imports at module load time
# Logger is configured once when this module is first imported.
def _configure_logger(log_level: str = "INFO") -> None:
    _logger.remove()  # Remove the default handler
    _logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    _logger.add(
        "logs/yuuka.log",
        level=log_level,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
    )


# Re-export the configured logger
logger = _logger
