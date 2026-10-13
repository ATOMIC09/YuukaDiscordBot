"""
tests/conftest.py
`bot.config` builds its singleton the moment it is imported, and it refuses to start without a
token and an API key. The values are set here, before any test module imports it.

`load_dotenv()` leaves variables that are already set alone, so a developer's own `.env` cannot
change what a test sees, provided every setting a test depends on is listed below.
"""

import os

_SETTINGS = {
    "BOT_TOKEN": "test-token",
    "OPENROUTER_API_KEY": "test-key",
    "OPENROUTER_SYSTEM_PROMPT": "You are Yuuka.",
    "TIMEZONE": "Asia/Bangkok",
    "STT_WAKE_WORDS": "ยูกะ,ยูคะ,ยุกะ,ยูกา,yuuka,yuka,yuuca,ゆうか,ゆか",
    "AGENT_MAX_ROUNDS": "8",
    "AGENT_MAX_TOOL_CALLS": "25",
    "MEMORY_OFFERS": "false",
}
for _key, _value in _SETTINGS.items():
    os.environ[_key] = _value
