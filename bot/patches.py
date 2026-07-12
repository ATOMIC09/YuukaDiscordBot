"""
bot/patches.py
Monkey-patches for pycord 2.8.0 compatibility.

Why this exists
---------------
pycord 2.8.0 introduced a new voice receive stack (discord.voice.receive) but
the old discord.sinks.Sink class was never updated to match its interface.
The new stack passes `VoiceData` objects to sink.write(), while the old sink
expects raw bytes. Several methods the new stack calls also don't exist on Sink.

Patches applied (all at the Sink class level — covers WaveSink, MP3Sink, etc.)
---------------
1. Sink.__sink_listeners__ = []
   → SinkEventRouter._register_listeners() accesses this attribute

2. Sink.walk_children()
   → SinkEventRouter.register_events() iterates over children

3. Sink.is_opus()
   → PacketDecoder.__init__ calls this to decide whether to run the Opus decoder.
     Old sinks always want decoded PCM, so always return False.

4. Sink.write(data, user) — THE CORE FIX
   → PacketRouter._do_run() calls: sink.write(voice_data, voice_data.source)
     where voice_data is a discord.voice.VoiceData object and voice_data.source
     is a User/Member (not an int).
   → Old Sink.write() does: BytesIO.write(voice_data) → TypeError!
   → Patched version extracts voice_data.pcm (bytes) and uses source.id (int)
     as the dict key (matching how sink.audio_data is later read back).

5. Suppress the stale RuntimeWarning from start_recording().
   DAVE is fully functional with davey installed — the warning is a leftover TODO.

6. Suppress the deprecated *args UserWarning from start_recording().

Call apply_patches() once at bot startup, BEFORE the bot connects to Discord.
"""

from __future__ import annotations

import io
import logging
import warnings

log = logging.getLogger(__name__)


def apply_patches() -> None:
    """Apply all pycord 2.8.0 compatibility patches. Call once before bot.run()."""

    # ------------------------------------------------------------------
    # Warning suppression
    # ------------------------------------------------------------------
    warnings.filterwarnings(
        "ignore",
        message="Voice reception is currently broken",
        category=RuntimeWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message="'args' parameter is deprecated",
        category=UserWarning,
    )

    # ------------------------------------------------------------------
    # Sink class patches
    # ------------------------------------------------------------------
    try:
        from discord.sinks.core import AudioData, Sink

        # Patch 1: __sink_listeners__
        if not hasattr(Sink, "__sink_listeners__"):
            Sink.__sink_listeners__ = []  # type: ignore[attr-defined]

        # Patch 2: walk_children()
        if not hasattr(Sink, "walk_children"):
            Sink.walk_children = lambda self: iter([])  # type: ignore[attr-defined]

        # Patch 3: is_opus()
        # PacketDecoder calls this to decide whether to Opus-decode incoming packets.
        # Old sinks always want decoded PCM (not raw Opus), so return False.
        if not hasattr(Sink, "is_opus"):
            Sink.is_opus = lambda self: False  # type: ignore[attr-defined]

        # Patch 4: write(data, user) — THE CORE FIX
        # The new PacketRouter passes write(VoiceData, User/Member).
        # Old Sink.write() tries to BytesIO.write(VoiceData) → TypeError.
        # We replace write() to extract VoiceData.pcm bytes and use source.id as key.
        _original_write = Sink.write.__wrapped__ if hasattr(Sink.write, "__wrapped__") else None

        def _patched_write(self, data, user):  # type: ignore[override]
            # data may be a VoiceData (new stack) or raw bytes (old stack)
            try:
                from discord.voice import VoiceData  # type: ignore[attr-defined]
                if isinstance(data, VoiceData):
                    # Skip packets where the SSRC hasn't been mapped to a user yet.
                    # These arrive at session start before Discord sends the SSRC→user
                    # mapping. Writing them would require int(None) → TypeError → crash.
                    if user is None:
                        return

                    pcm: bytes = data.pcm
                    if not pcm:
                        return  # Silence/empty frame — nothing to record

                    # Use the integer user ID as the key so the callback can call
                    # self.bot.get_user(user_id) later.
                    uid: int = user.id if hasattr(user, "id") else int(user)
                    if uid not in self.audio_data:
                        self.audio_data[uid] = AudioData(io.BytesIO())
                    self.audio_data[uid].write(pcm)
                    return
            except ImportError:
                pass

            # Fallback: old-style bytes data
            if user is None:
                return
            if user not in self.audio_data:
                self.audio_data[user] = AudioData(io.BytesIO())
            self.audio_data[user].write(data)

        Sink.write = _patched_write  # type: ignore[method-assign]

    except ImportError:
        log.warning("Could not patch discord.sinks.Sink — voice receive may fail")

    log.info("Applied pycord patches")
