"""
bot/logger.py
Configures the shared loguru logger for the entire project.
All modules should import `logger` from here:

    from bot.logger import logger
"""

import logging
import os
import sys

from loguru import logger as _logger


class InterceptHandler(logging.Handler):
    """Logs standard library log messages through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Aggressively filter out annoying framework warnings before they reach Loguru
        if record.name.startswith(("nemo", "nv_one_logger", "lhotse", "numexpr")):
            if record.levelno < logging.ERROR:
                return

        # Get corresponding Loguru level if it exists.
        try:
            level = _logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        try:
            frame = sys._getframe(6)
            depth = 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
        except ValueError:
            depth = 0

        _logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


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
        colorize=False if os.environ.get("NO_COLOR") else None,
    )
    _logger.add(
        "logs/yuuka.log",
        level=log_level,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
    )

    # Intercept standard library logging and pipe it to loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Silence noisy standard library loggers
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("graphviz").setLevel(logging.WARNING)


# Re-export the configured logger
logger = _logger

