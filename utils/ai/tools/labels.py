"""
utils/ai/tools/labels.py
One short line per tool call for the progress embed (`utils/ai/progress.py`): what she
is about to do, in words the room understands, not a tool name and its JSON.
"""

from __future__ import annotations

from typing import Callable

_MAX = 80

# The same animated emoji the chat command's status uses (tools/search.py).
_MAGNIFIER = "<a:MagnifierGIF:1052563354910216252>"
_LOADING = "<a:AppleLoadingGIF:1052465926487953428>"


def _clip(text: object) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _MAX else text[: _MAX - 1] + "…"


def _web_search(a: dict) -> str:
    # Reading one result of an earlier search is not a new search: it comes from the cache.
    if a.get("result_index") is not None:
        return f"{_LOADING} อ่านผลลัพธ์ที่ {int(a['result_index']) + 1} ของ: {_clip(a.get('query', ''))}"
    return f"{_MAGNIFIER} ค้นเว็บ: {_clip(a.get('query', ''))}"


_LABELS: dict[str, Callable[[dict], str]] = {
    "web_search": _web_search,
    "read_messages": lambda a: f"📖 อ่านข้อความใน {_clip(a.get('channel') or 'ช่องนี้')}",
    "search_messages": lambda a: f"📖 ค้นข้อความ: {_clip(a.get('query', ''))}",
    "voice_members": lambda a: "👥 ดูว่าใครอยู่ในห้องเสียง",
    "user_info": lambda a: f"👤 ดูข้อมูลของ {_clip(a.get('member', ''))}",
    "server_info": lambda a: "🏢 ดูข้อมูลเซิร์ฟเวอร์",
    "music_play": lambda a: f"🎵 เปิดเพลง: {_clip(a.get('query', ''))}",
    "music_skip": lambda a: "⏭️ ข้ามเพลง" + (f" ไปเพลง {_clip(a['song'])}" if a.get("song") else (f" ไปลำดับที่ {a['position']}" if a.get("position") else "")),
    "music_stop": lambda a: "⏹️ หยุดเพลงและล้างคิว",
    "music_pause": lambda a: "⏸️ พักเพลง",
    "music_resume": lambda a: "▶️ เล่นเพลงต่อ",
    "music_seek": lambda a: f"⏩ เลื่อนไปที่ {_clip(a.get('timestamp', ''))}",
    "music_previous": lambda a: "⏮️ ย้อนไปเพลงก่อนหน้า",
    "music_loop": lambda a: f"🔁 ตั้งวนลูป: {_clip(a.get('mode', ''))}",
    "music_volume": lambda a: f"🔊 ปรับเสียงเป็น {_clip(a.get('level', ''))}%",
    "music_leave": lambda a: "👋 ออกจากห้องเสียง",
    "music_now_playing": lambda a: "🎵 ดูเพลงที่กำลังเล่น",
    "music_queue": lambda a: "📜 ดูคิวเพลง",
    "music_history": lambda a: "📜 ดูเพลงที่เล่นไปแล้ว",
    "music_remove": lambda a: f"🗑️ เอาเพลงลำดับที่ {_clip(a.get('position', ''))} ออกจากคิว",
    "voice_kick": lambda a: f"🦵 เตะ {_clip(a.get('member', ''))} ออกจากห้องเสียง",
    "voice_disconnect_timer": lambda a: f"⏰ ตั้งเวลาตัดการเชื่อมต่อ {_clip(a.get('seconds', ''))} วินาที",
    "attendance": lambda a: "📝 เช็คชื่อคนในห้องเสียง",
    "absent": lambda a: "🔎 หาผู้ขาดประชุม" + (f" ({_clip(a['role'])})" if a.get("role") else ""),
    "record_start": lambda a: "🔴 เริ่มอัดเสียง",
    "record_stop": lambda a: "⏹️ หยุดอัดเสียง",
    "transcribe_start": lambda a: "🎙️ เริ่มถอดเสียง",
    "transcribe_stop": lambda a: "⏹️ หยุดถอดเสียง",
    "remind_me": lambda a: f"⏰ ตั้งเตือนอีก {_clip(a.get('minutes', ''))} นาที: {_clip(a.get('text', ''))}",
    "notify_when_joins_voice": lambda a: f"🔔 รอเตือนเมื่อ {_clip(a.get('member', ''))} เข้าห้องเสียง",
    # What is being kept or forgotten is never shown: the line is read aloud to a room.
    "memory_save": lambda a: "📒 จดลงสมุดความจำ",
    "memory_search": lambda a: f"🔎 เปิดสมุดความจำ: {_clip(a.get('query', ''))}".rstrip(": "),
    "memory_forget": lambda a: "🗑️ ลบออกจากสมุดความจำ",
    "wait": lambda a: f"⏳ รอ {_clip(a.get('seconds') or 10)} วินาที",
}


def describe_call(name: str, args: dict) -> str:
    """The line shown for one planned call. Unknown tools fall back to their name."""
    make = _LABELS.get(name)
    if make is None:
        return f"⚙️ {name}"
    try:
        return make(args)
    except Exception:
        # A label must never break a turn.
        return f"⚙️ {name}"
