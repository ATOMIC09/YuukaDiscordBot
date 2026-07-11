"""
bot/patches.py
Monkey-patches for pycord 2.8.0 compatibility.

Why this exists
---------------
pycord 2.8.0 ships with two regressions in voice receive:

1. `discord.sinks.Sink` is missing `__sink_listeners__` and `walk_children()`.
   The new `SinkEventRouter` (in discord.voice.receive) accesses both, but the
   old Sink class was never updated as part of the 2.8 refactor.

2. `VoiceClient.start_recording()` still fires a `RuntimeWarning` that says
   "Voice reception is currently broken due to DAVE". This warning is a stale
   TODO that was never cleaned up — DAVE is fully functional when the `davey`
   package is installed (which it is in this project: HAS_DAVEY = True).

Patches applied
---------------
- Sink.__sink_listeners__ = []         → satisfies SinkEventRouter._register_listeners()
- Sink.walk_children = lambda: iter([]) → satisfies SinkEventRouter.register_events()
- Suppress the stale DAVE RuntimeWarning from start_recording()
- Suppress the deprecated *args UserWarning from start_recording()

Call apply_patches() once at bot startup, BEFORE the bot connects to Discord.
"""

from __future__ import annotations

import logging
import warnings

log = logging.getLogger(__name__)


def apply_patches() -> None:
    """Apply all pycord 2.8.0 compatibility patches. Call once before bot.run()."""

    # ------------------------------------------------------------------
    # Patch 1: Suppress the stale RuntimeWarning from start_recording().
    # pycord#3139 warning was never removed after the DAVE fix landed.
    # With davey installed, voice receive works — the warning is misleading.
    # ------------------------------------------------------------------
    warnings.filterwarnings(
        "ignore",
        message="Voice reception is currently broken",
        category=RuntimeWarning,
    )

    # ------------------------------------------------------------------
    # Patch 2: Suppress the deprecated *args UserWarning.
    # Our listener.py already uses the new single-param callback — but
    # suppress globally for any other code paths.
    # ------------------------------------------------------------------
    warnings.filterwarnings(
        "ignore",
        message="'args' parameter is deprecated",
        category=UserWarning,
    )

    # ------------------------------------------------------------------
    # Patch 3: Add __sink_listeners__ and walk_children() to the old Sink.
    # SinkEventRouter (discord.voice.receive.router) expects both, but
    # discord.sinks.Sink (the legacy base class) was never updated.
    # Patching at the class level covers all subclasses (WaveSink, MP3Sink, etc.)
    # ------------------------------------------------------------------
    try:
        from discord.sinks.core import Sink

        if not hasattr(Sink, "__sink_listeners__"):
            Sink.__sink_listeners__ = []  # type: ignore[attr-defined]

        if not hasattr(Sink, "walk_children"):
            Sink.walk_children = lambda self: iter([])  # type: ignore[attr-defined]

    except ImportError:
        log.warning("Could not patch discord.sinks.Sink — voice receive may fail")

    log.info("Applied pycord patches")
