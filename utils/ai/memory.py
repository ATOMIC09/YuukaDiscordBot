"""
utils/ai/memory.py
Server memory: what Yuuka was asked to remember, kept as messages in a hidden channel of the
server itself, so nothing about a server or its members is stored where the bot runs.

Discord is the database. One note is one embed in the server's memory channel (found again by
a marker in its topic) and everything here is a RAM copy, read back after a restart. The server
owns the data: an admin reads it there, deleting a message makes her forget that note and
deleting the channel wipes everything.

The graph: a note is an edge between the entities it is about (a name, or a member by id), and
recall follows one hop.

What keeps it private is `MemoryStore.audience_ok`: a note is only used where everyone who could
see the reply can also read the channel the note was said in. Nothing in this module logs a
note's text, only counts and ids.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Iterable

import discord
from rapidfuzz import fuzz

from bot.config import config
from bot.logger import logger
from utils import wake
from utils.embeds import COLOR_INFO, COLOR_WARNING, build_embed
from utils.errors import UserWarning

# The topic of the memory channel starts with this: it is how she finds the channel again, so
# not even its id is kept anywhere.
MARKER = "[yuuka-memory]"
CHANNEL_NAME = "yuuka-memory"

# Only her own embeds with one of these footers are read back. The "v1" is the format, so a
# later one can still read an older note.
FACT_FOOTER = "yuuka-memory:fact:v1"
OPTOUT_FOOTER = "yuuka-memory:optout:v1"
_ABOUT_FIELD, _SOURCE_FIELD, _AUTHOR_FIELD, _MEMBER_FIELD = "เกี่ยวกับ", "จากช่อง", "บอกโดย", "สมาชิก"

MAX_FACT_CHARS = 300
MAX_ABOUT = 5
_MAX_NAME_CHARS = 40

_USER_REF = re.compile(r"<@!?(\d+)>")
_MEMBER_LINE = re.compile(r"^<@!?(\d+)>$")
_CHANNEL_REF = re.compile(r"<#(\d+)>")

# How long an answer to "can everyone here read that channel" is reused. Permission edits
# clear it sooner (the cog's listeners); this only bounds a missed one.
_AUDIENCE_TTL_S = 300
# After Discord refuses access to the memory channel, wait this long before trying again.
_BLOCKED_S = 300


# ── Names and text ────────────────────────────────────────────────────────

def entity_key(name: str) -> str:
    """How two spellings of a name are compared: tone marks, spacing, case and kana folded."""
    return wake.normalize(name)


def clean_name(text: str) -> str:
    """A name as it is stored: one line, no mention syntax, short."""
    text = " ".join(text.replace("<", "").replace(">", "").split()).lstrip("@").strip()
    return text[:_MAX_NAME_CHARS].strip()


def _member_names(member: discord.Member) -> list[str]:
    names = [member.display_name, member.name, getattr(member, "global_name", None)]
    return [n for n in names if n]


# Dates and times are not what the digit rule is after.
_DATE_TIME = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2}:\d{2}(?::\d{2})?")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Nine or more digits, even when a phone or card number is spaced or dashed.
_DIGIT_RUN = re.compile(r"\d(?:[\s-]?\d){8,}")
# A long unbroken run of letters and digits is a key or a token, not a word.
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9_\-]{32,}")
_SECRET_WORD = re.compile(
    r"password|passwd|passcode|api[ _-]?key|รหัสผ่าน|พาสเวิร์ด|พาสเวิด|เลขบัตร|บัตรเครดิต", re.I
)


def looks_private(text: str) -> bool:
    """Obvious private data (an email, a phone or card number, a key, a password) she must not keep."""
    text = _DATE_TIME.sub(" ", text)
    return bool(
        _EMAIL.search(text) or _DIGIT_RUN.search(text) or _TOKEN_LIKE.search(text) or _SECRET_WORD.search(text)
    )


def is_memory_channel(channel: object) -> bool:
    """Whether `channel` is a server's memory channel, which no tool may read out."""
    topic = getattr(channel, "topic", None)
    return bool(topic) and MARKER in topic


# ── Notes ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Note:
    id: int  # the id of the message that holds it
    text: str
    names: tuple[str, ...]  # entities that are plain names
    members: tuple[int, ...]  # entities that are members, by id
    source_id: int  # the channel it was said in
    author_id: int  # who asked her to keep it
    created: datetime
    # Derived once, because recall compares every note on every turn.
    text_key: str = field(init=False, repr=False, compare=False)
    keys: tuple[str, ...] = field(init=False, repr=False, compare=False)
    blob: str = field(init=False, repr=False, compare=False)
    entities: frozenset = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        text_key = entity_key(self.text)
        keys = tuple(dict.fromkeys(k for k in map(entity_key, self.names) if k))
        object.__setattr__(self, "text_key", text_key)
        object.__setattr__(self, "keys", keys)
        object.__setattr__(self, "blob", " ".join((text_key, *keys)))
        object.__setattr__(
            self, "entities", frozenset({("n", k) for k in keys} | {("m", m) for m in self.members})
        )


@dataclass(frozen=True)
class Optout:
    member_id: int
    message_id: int


def note_embed(text: str, names: Iterable[str], members: Iterable[int], source_id: int, author_id: int) -> discord.Embed:
    """What is written to the memory channel: readable by an admin, parsed back by `parse_message`."""
    about = [f"<@{m}>" for m in members] + list(names)
    return build_embed(
        "📒 โน้ต",
        text,
        COLOR_INFO,
        footer=FACT_FOOTER,
        fields=[
            (_ABOUT_FIELD, "\n".join(about), True),
            (_SOURCE_FIELD, f"<#{source_id}>", True),
            (_AUTHOR_FIELD, f"<@{author_id}>", True),
        ],
    )


def optout_embed(member_id: int) -> discord.Embed:
    return build_embed(
        "🚫 ไม่ให้หนูจำ",
        "สมาชิกคนนี้ขอให้หนูไม่จำเรื่องของเขา",
        COLOR_WARNING,
        footer=OPTOUT_FOOTER,
        fields=[(_MEMBER_FIELD, f"<@{member_id}>", True)],
    )


def parse_message(message: discord.Message, bot_id: int) -> Note | Optout | None:
    """The note or opt-out record a message holds. Only her own embeds count, so nobody else
    can add one by posting in the channel."""
    if message.author.id != bot_id or not message.embeds:
        return None
    embed = message.embeds[0]
    kind = getattr(embed.footer, "text", None)
    fields = {f.name: f.value or "" for f in embed.fields}

    if kind == OPTOUT_FOOTER:
        found = _USER_REF.search(fields.get(_MEMBER_FIELD, ""))
        return Optout(int(found.group(1)), message.id) if found else None
    if kind != FACT_FOOTER:
        return None

    source = _CHANNEL_REF.search(fields.get(_SOURCE_FIELD, ""))
    author = _USER_REF.search(fields.get(_AUTHOR_FIELD, ""))
    text = (embed.description or "").strip()
    if not (source and author and text):
        return None

    names: list[str] = []
    members: list[int] = []
    for line in fields.get(_ABOUT_FIELD, "").splitlines():
        line = line.strip()
        if not line:
            continue
        mention = _MEMBER_LINE.match(line)
        if mention:
            members.append(int(mention.group(1)))
        else:
            names.append(line)
    if not (names or members):
        return None
    return Note(
        message.id, text, tuple(names), tuple(members), int(source.group(1)), int(author.group(1)), message.created_at
    )


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def search(notes: Iterable[Note], query: str, limit: int = 15) -> list[Note]:
    """The notes that match `query`: best first, newest first among equals. An empty query lists
    the newest. Each word counts if it appears in the note or its names. Thai has no spaces, so a
    long phrase that matched no word falls back to how much of it (as pairs of letters) the note
    shares: "what does the team play on Friday" finds "the team plays Valorant every Friday night",
    where one contiguous match would not."""
    ordered = sorted(notes, key=lambda n: n.id, reverse=True)
    if not query.strip():
        return ordered[:limit]
    words = [k for k in map(entity_key, query.split()) if len(k) >= 2]
    whole = entity_key(query)
    grams = _bigrams(whole) if len(whole) >= 6 else set()
    ranked: list[tuple[float, Note]] = []
    for note in ordered:
        score = float(sum(1 for k in words if k in note.blob))
        if not score and grams:
            shared = len(grams & _bigrams(note.blob)) / len(grams)
            score = shared if shared >= 0.6 else 0.0  # always below a word match
        if score:
            ranked.append((score, note))
    ranked.sort(key=lambda pair: -pair[0])  # stable, so equal scores stay newest first
    return [note for _, note in ranked[:limit]]


# ── Who can read what ─────────────────────────────────────────────────────

def can_read(member: discord.Member, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
    """Whether `member` can open `channel` and read its history, from the cache alone.

    A private thread's members are not always cached, so one that is missing is treated as not
    in it: when in doubt, nothing is shared."""
    if isinstance(channel, discord.Thread) and channel.parent is None:
        return False
    perms = channel.permissions_for(member)
    if not (perms.view_channel and perms.read_message_history):
        return False
    if isinstance(channel, discord.Thread) and channel.is_private():
        return perms.manage_threads or any(m.id == member.id for m in channel.members)
    return True


def _audience_id(channel: discord.abc.GuildChannel | discord.Thread) -> int:
    """Channels with the same audience share an id: a public thread is its parent's."""
    if isinstance(channel, discord.Thread) and not channel.is_private():
        return channel.parent_id
    return channel.id


def _viewers(guild: discord.Guild, place: discord.abc.GuildChannel | discord.Thread) -> list[discord.Member]:
    """Everyone who could see a message posted in `place`. A thread takes its parent's people,
    which is the larger group, so a doubt errs on the side of sharing less."""
    base = place.parent if isinstance(place, discord.Thread) else place
    humans = [m for m in guild.members if not m.bot]
    if base is None:
        return humans
    return [m for m in humans if base.permissions_for(m).view_channel]


# ── The store ─────────────────────────────────────────────────────────────

@dataclass
class GuildMemory:
    guild_id: int
    channel_id: int
    notes: dict[int, Note] = field(default_factory=dict)  # oldest first
    optouts: dict[int, set[int]] = field(default_factory=dict)  # member id → their record messages
    loaded: bool = False
    blocked_until: float = 0.0
    blocked_reason: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MemoryStore:
    """Every server's notes, as read back from its memory channel.

    Reads from RAM are synchronous. Anything that writes goes to Discord first and RAM second,
    so a failed write leaves them agreeing."""

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self._guilds: dict[int, GuildMemory] = {}
        self._audience: dict[tuple[int, int], tuple[float, bool]] = {}

    # ── finding and loading ───────────────────────────────────────────────

    def channel_for(self, guild: discord.Guild) -> discord.TextChannel | None:
        """The server's memory channel (the oldest, if somebody marked several), from the cache."""
        found = [c for c in guild.text_channels if is_memory_channel(c)]
        return min(found, key=lambda c: c.id) if found else None

    def _block(self, mem: GuildMemory, reason: str) -> UserWarning:
        mem.blocked_until = time.monotonic() + _BLOCKED_S
        mem.blocked_reason = reason
        logger.warning(f"[Memory] Guild {mem.guild_id}: the memory channel cannot be used right now")
        return UserWarning("ใช้สมุดความจำไม่ได้ค่ะ", reason)

    def _lost_access(self, mem: GuildMemory, channel: discord.abc.GuildChannel) -> UserWarning:
        return self._block(
            mem,
            f"หนูอ่านหรือเขียนในช่อง {channel.mention} ไม่ได้แล้วค่ะ ช่วยตรวจสิทธิ์ของหนูในช่องนั้นหน่อยนะคะ",
        )

    async def ensure_loaded(self, guild: discord.Guild) -> GuildMemory:
        """The server's notes, read from its memory channel the first time they are needed.

        Raises UserWarning when there is no memory channel or it cannot be used."""
        channel = self.channel_for(guild)
        if channel is None:
            self._guilds.pop(guild.id, None)
            raise UserWarning("ยังไม่มีสมุดความจำค่ะ", "ให้แอดมินสร้างด้วย `/memory setup` ก่อนนะคะ (´・ω・`)")
        mem = self._guilds.get(guild.id)
        if mem is None or mem.channel_id != channel.id:
            mem = self._guilds[guild.id] = GuildMemory(guild.id, channel.id)
        if time.monotonic() < mem.blocked_until:
            raise UserWarning("ใช้สมุดความจำไม่ได้ค่ะ", mem.blocked_reason)
        if not mem.loaded:
            async with mem.lock:
                if not mem.loaded:
                    await self._load(channel, mem)
        return mem

    async def _load(self, channel: discord.TextChannel, mem: GuildMemory) -> None:
        # Newest first and bounded: the channel holds notes, opt-outs and one intro, so this is
        # far more than it should ever hold, and a channel somebody floods cannot stall a reply.
        limit = config.memory_max_facts * 2 + 200
        notes: dict[int, Note] = {}
        optouts: dict[int, set[int]] = {}
        scanned = 0
        try:
            async for message in channel.history(limit=limit):
                scanned += 1
                parsed = parse_message(message, self.bot.user.id)
                if isinstance(parsed, Note):
                    notes[parsed.id] = parsed
                elif isinstance(parsed, Optout):
                    optouts.setdefault(parsed.member_id, set()).add(parsed.message_id)
        except discord.Forbidden:
            raise self._lost_access(mem, channel)
        if scanned >= limit:
            logger.warning(f"[Memory] Guild {mem.guild_id}: the memory channel has more than {limit} messages; the oldest were not read")
        mem.notes = dict(sorted(notes.items()))
        mem.optouts = optouts
        mem.loaded = True
        logger.info(f"[Memory] Loaded {len(notes)} notes and {len(optouts)} opt-outs for guild {mem.guild_id}")

    def forget_guild(self, guild_id: int) -> None:
        """Drop a server's RAM copy (the bot left); the next use reads it afresh."""
        self._guilds.pop(guild_id, None)
        self.clear_audience()

    def drop_if_channel(self, guild_id: int, channel_id: int) -> None:
        """Drop the RAM copy if `channel_id` is the channel it was read from (deleted, or no longer marked)."""
        mem = self._guilds.get(guild_id)
        if mem is not None and mem.channel_id == channel_id:
            self.forget_guild(guild_id)
            logger.info(f"[Memory] Guild {guild_id}: the memory channel is gone, notes dropped from RAM")

    def on_deleted(self, guild_id: int, channel_id: int, message_ids: Iterable[int]) -> None:
        """Messages were deleted in some channel: if it is a memory channel, those notes are forgotten."""
        mem = self._guilds.get(guild_id)
        if mem is None or mem.channel_id != channel_id:
            return
        gone = 0
        for message_id in message_ids:
            gone += mem.notes.pop(message_id, None) is not None
            for records in mem.optouts.values():
                records.discard(message_id)
        mem.optouts = {member: records for member, records in mem.optouts.items() if records}
        if gone:
            logger.info(f"[Memory] Guild {guild_id}: {gone} notes deleted in the memory channel")

    # ── reading ───────────────────────────────────────────────────────────

    def notes(self, guild_id: int) -> list[Note]:
        """Every note of a server that is loaded, newest first."""
        mem = self._guilds.get(guild_id)
        return list(reversed(mem.notes.values())) if mem else []

    def about_or_by(self, guild_id: int, member_id: int) -> list[Note]:
        """Notes that are about a member or were told by them, newest first."""
        return [n for n in self.notes(guild_id) if member_id in n.members or n.author_id == member_id]

    def is_opted_out(self, guild_id: int, member_id: int) -> bool:
        mem = self._guilds.get(guild_id)
        return bool(mem and member_id in mem.optouts)

    # ── who may see what ──────────────────────────────────────────────────

    def clear_audience(self) -> None:
        self._audience.clear()

    def audience_ok(
        self,
        guild: discord.Guild,
        source_id: int,
        place: discord.abc.GuildChannel | discord.Thread,
        extra: Iterable[discord.Member] = (),
    ) -> bool:
        """Whether a note from channel `source_id` may be used in `place`.

        Everyone who can see `place`, and everyone in `extra` (the people in a voice call, who hear
        the reply), has to be able to read the channel the note was said in. A source that is gone
        or not cached counts as not readable: the note stays for an admin to delete."""
        if not isinstance(place, (discord.abc.GuildChannel, discord.Thread)):
            return False
        source = guild.get_channel_or_thread(source_id)
        if source is None:
            return False
        if not self._viewers_can_read(guild, source, place):
            return False
        return all(can_read(m, source) for m in extra if not m.bot)

    def _viewers_can_read(self, guild: discord.Guild, source, place) -> bool:
        key = (source.id, place.id)
        now = time.monotonic()
        hit = self._audience.get(key)
        if hit and hit[0] > now:
            return hit[1]
        if _audience_id(source) == _audience_id(place):
            ok = True  # the same people, by definition
        else:
            ok = all(can_read(m, source) for m in _viewers(guild, place))
        if len(self._audience) > 1000:
            self._audience = {k: v for k, v in self._audience.items() if v[0] > now}
        self._audience[key] = (now + _AUDIENCE_TTL_S, ok)
        return ok

    # ── writing ───────────────────────────────────────────────────────────

    def _check_new(
        self,
        guild: discord.Guild,
        mem: GuildMemory,
        channel: discord.TextChannel,
        *,
        text: str,
        names: list[str],
        members: list[int],
        source: discord.abc.GuildChannel | discord.Thread,
        author: discord.Member,
    ) -> None:
        """Everything that can make her refuse a note, without writing anything."""
        if author.id in mem.optouts:
            raise UserWarning("เซนเซย์ตั้งไว้ว่าไม่ให้หนูจำค่ะ", "ถ้าเปลี่ยนใจ ใช้ `/memory optin` ได้เลยนะคะ")

        name_keys = {entity_key(n) for n in names}
        text_key = entity_key(text)
        for member_id in mem.optouts:
            member = guild.get_member(member_id)
            named = member_id in members or (
                member is not None
                and any(
                    len(k) >= 2 and (k in name_keys or (len(k) >= 3 and k in text_key))
                    for k in map(entity_key, _member_names(member))
                )
            )
            if named:
                # Not who: that is their business.
                raise UserWarning("จดเรื่องนี้ไม่ได้ค่ะ", "มีสมาชิกที่ขอให้หนูไม่จำเรื่องของเขาค่ะ")

        if len(mem.notes) >= config.memory_max_facts:
            raise UserWarning(
                "สมุดเต็มแล้วค่ะ",
                f"หนูจำได้สูงสุด {config.memory_max_facts} เรื่องต่อเซิร์ฟเวอร์ ให้หนูลืมบางเรื่องก่อนนะคะ "
                "(`/memory forget` หรือลบข้อความในช่องความจำก็ได้ค่ะ)",
            )
        if text_key and any(old.text_key == text_key or fuzz.ratio(old.text_key, text_key) >= 92 for old in mem.notes.values()):
            raise UserWarning("หนูจำเรื่องนี้ไว้แล้วค่ะ", "ไม่ต้องจดซ้ำนะคะ (๑•̀ᴗ•́)و")
        # The channel she writes to must not show a note to anyone who could not read where it was said.
        if not self.audience_ok(guild, source.id, channel):
            raise UserWarning(
                "จดเรื่องนี้ไม่ได้ค่ะ",
                "ช่องความจำมีคนที่อ่านช่องนี้ไม่ได้ หนูเลยไม่เอาเรื่องจากช่องนี้ไปจดไว้ที่นั่นนะคะ "
                "(ช่องความจำควรให้เห็นแค่แอดมินค่ะ)",
            )

    async def save(
        self,
        guild: discord.Guild,
        *,
        text: str,
        names: list[str],
        members: list[int],
        source: discord.abc.GuildChannel | discord.Thread,
        author: discord.Member,
        before_write: Callable[[], Awaitable[None]] | None = None,
    ) -> Note:
        """Write a note to the memory channel. Raises UserWarning to refuse.

        `before_write` runs once the note has passed every check, just before it is written."""
        mem = await self.ensure_loaded(guild)
        channel = guild.get_channel(mem.channel_id)
        check = dict(text=text, names=names, members=members, source=source, author=author)
        self._check_new(guild, mem, channel, **check)
        if before_write is not None:
            await before_write()
        async with mem.lock:
            # Another note may have landed while this one was being announced.
            self._check_new(guild, mem, channel, **check)
            try:
                message = await channel.send(
                    embed=note_embed(text, names, members, source.id, author.id),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                raise self._lost_access(mem, channel)
            except discord.HTTPException:
                raise UserWarning("จดไม่สำเร็จค่ะ", "คุยกับ Discord ไม่สำเร็จ ลองใหม่อีกทีนะคะ (´-ω-`)")
            note = Note(message.id, text, tuple(names), tuple(members), source.id, author.id, message.created_at)
            mem.notes[note.id] = note
        logger.info(f"[Memory] Guild {guild.id}: saved note {note.id} ({len(mem.notes)} in all)")
        return note

    async def delete(self, guild: discord.Guild, note_id: int) -> bool:
        """Delete one note. False if it was already gone."""
        mem = await self.ensure_loaded(guild)
        channel = guild.get_channel(mem.channel_id)
        try:
            await channel.get_partial_message(note_id).delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            raise self._lost_access(mem, channel)
        except discord.HTTPException:
            raise UserWarning("ลืมไม่สำเร็จค่ะ", "คุยกับ Discord ไม่สำเร็จ ลองใหม่อีกทีนะคะ (´-ω-`)")
        existed = mem.notes.pop(note_id, None) is not None
        if existed:
            logger.info(f"[Memory] Guild {guild.id}: deleted note {note_id}")
        return existed

    async def forget_member(self, guild: discord.Guild, member_id: int) -> int:
        """Delete every note about a member or told by them. Returns how many."""
        await self.ensure_loaded(guild)
        count = 0
        for note in self.about_or_by(guild.id, member_id):
            count += await self.delete(guild, note.id)
        return count

    async def add_optout(self, guild: discord.Guild, member_id: int) -> None:
        mem = await self.ensure_loaded(guild)
        if member_id in mem.optouts:
            return
        channel = guild.get_channel(mem.channel_id)
        async with mem.lock:
            try:
                message = await channel.send(
                    embed=optout_embed(member_id), allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.Forbidden:
                raise self._lost_access(mem, channel)
            mem.optouts.setdefault(member_id, set()).add(message.id)
        logger.info(f"[Memory] Guild {guild.id}: a member opted out")

    async def remove_optout(self, guild: discord.Guild, member_id: int) -> bool:
        """Lift an opt-out. False if there was none."""
        mem = await self.ensure_loaded(guild)
        records = mem.optouts.get(member_id)
        if not records:
            return False
        channel = guild.get_channel(mem.channel_id)
        for message_id in list(records):
            try:
                await channel.get_partial_message(message_id).delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                raise self._lost_access(mem, channel)
        mem.optouts.pop(member_id, None)
        logger.info(f"[Memory] Guild {guild.id}: a member opted back in")
        return True

    # ── recall ────────────────────────────────────────────────────────────

    def recall(
        self,
        guild: discord.Guild,
        request: str,
        speaker_id: int | None,
        usable: Callable[[Note], bool],
        limit: int,
    ) -> list[Note]:
        """The notes worth putting in front of a request, most relevant first.

        In this order: notes whose names (or a member's current names) appear in the request, up to
        three about the speaker, then notes one hop away: those that share an entity with a note the
        request itself named. The hop never goes through the speaker, or a greeting from someone
        with many notes would pull in all of them. Only notes `usable` accepts are returned, at
        most `limit`."""
        notes = self.notes(guild.id)
        req = entity_key(request)
        if limit <= 0 or not notes:
            return []
        member_keys: dict[int, tuple[str, ...]] = {}

        def keys_of(member_id: int) -> tuple[str, ...]:
            if member_id not in member_keys:
                member = guild.get_member(member_id)
                found = map(entity_key, _member_names(member)) if member else ()
                member_keys[member_id] = tuple(k for k in found if len(k) >= 2)
            return member_keys[member_id]

        def mentioned(note: Note) -> bool:
            for key in note.keys:
                if len(key) < 2:
                    continue
                # A name read back by speech recognition is rarely spelled the same, but a
                # request shorter than the name would match any part of it.
                if key in req or (len(key) >= 4 and len(req) >= len(key) and fuzz.partial_ratio(key, req) >= 90):
                    return True
            return any(k in req for m in note.members for k in keys_of(m))

        picked: list[Note] = []
        seen: set[int] = set()

        def take(note: Note) -> None:
            if note.id not in seen and usable(note):
                seen.add(note.id)
                picked.append(note)

        for note in notes:
            if mentioned(note):
                take(note)
        named = list(picked)
        if speaker_id is not None:
            for note in [n for n in notes if speaker_id in n.members][:3]:
                take(note)
        linked = frozenset().union(*(n.entities for n in named)) - {("m", speaker_id)}
        for note in notes:
            if note.id not in seen and note.entities & linked:
                take(note)
        return picked[:limit]

    def related(
        self, guild: discord.Guild, found: list[Note], pool: list[Note], skip: Iterable[str] = ()
    ) -> list[tuple[str, int]]:
        """The entities `found` talks about, each with how many notes of `pool` mention it: where
        to look next. Names already in the query (`skip`) and members who left are left out."""
        skipped = {k for k in map(entity_key, skip) if k}
        labels: dict[tuple[str, object], str] = {}
        for note in found:
            for name in note.names:
                if (key := entity_key(name)) and key not in skipped:
                    labels.setdefault(("n", key), name)
            for member_id in note.members:
                member = guild.get_member(member_id)
                if member is not None and not any(entity_key(n) in skipped for n in _member_names(member)):
                    labels.setdefault(("m", member_id), member.display_name)
        counts = [(label, sum(1 for n in pool if entity in n.entities)) for entity, label in labels.items()]
        return sorted(counts, key=lambda pair: (-pair[1], pair[0]))
