# This file makes the directory a package.
# The shared `ai` SlashCommandGroup is defined here so both chat.py and
# voice_chat.py can attach their sub-commands to the same /ai group without
# circular imports.

import discord

ai_group = discord.SlashCommandGroup("ai", "🤖 คำสั่งเกี่ยวกับระบบ AI")
