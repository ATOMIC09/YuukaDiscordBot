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

        # ------------------------------------------------------------------
        # DAVE Voice Receive Patches
        try:
            from discord.opus import PacketDecoder, OpusError
            from discord.voice.receive.reader import PacketDecryptor, OPUS_SILENCE, _log as reader_log, davey
            from discord.voice.receive.router import PacketRouter
            import nacl.secret

            # Patch 1: PacketDecoder._decode_packet (opus.py)
            def _patched_decode_packet(self, packet):
                assert self._decoder is not None
                assert self.sink.client

                user_id = self._cached_id
                dave = self.sink.client._connection.dave_session
                in_dave = dave is not None

                reader_log.debug(
                    "Decrypting packet for user %s (DAVE enabled: %s). Has decrypted data?: %s",
                    user_id,
                    in_dave,
                    packet.decrypted_data is not None,
                )

                other_code = True

                if packet:
                    other_code = False
                    pcm = self._decoder.decode(packet.decrypted_data, fec=False)

                if other_code:
                    next_packet = self._buffer.peek_next()

                    if next_packet is not None:
                        nextdata = next_packet.decrypted_data
                        reader_log.debug(
                            "Generating fec packet: fake=%s, fec=%s",
                            packet.sequence,
                            next_packet.sequence,
                        )
                        pcm = self._decoder.decode(nextdata, fec=True)
                    else:
                        pcm = self._decoder.decode(None, fec=False)

                return packet, pcm
                
            PacketDecoder._decode_packet = _patched_decode_packet

            # Patch 2: PacketDecryptor.decrypt_rtp (reader.py)
            def _patched_decrypt_rtp(self, packet):
                state = self.client._connection
                dave = state.dave_session

                raw_payload = self._decryptor_rtp(packet)

                if dave is not None and dave.ready:
                    uid = state.ssrc_user_map.get(packet.ssrc)
                    decrypted = False

                    if not uid:
                        # SSRC->user_id mapping not yet populated (race with member_connect).
                        # Try every user ID known to the DAVE session until one decrypts.
                        for candidate_uid in dave.get_user_ids():
                            try:
                                decrypted_audio = dave.decrypt(
                                    candidate_uid,
                                    davey.MediaType.audio,
                                    raw_payload,
                                )
                                # Successfully decrypted — cache the mapping for next time
                                self.client._connection.user_ssrc_map[candidate_uid] = packet.ssrc
                                uid = candidate_uid
                                packet.decrypted_data = decrypted_audio
                                decrypted = True
                                reader_log.debug(
                                    "DAVE: inferred ssrc %s -> user_id %s from decryption",
                                    packet.ssrc, uid,
                                )
                                break
                            except Exception:
                                continue

                    if uid and not decrypted:
                        try:
                            decrypted_audio = dave.decrypt(
                                uid,
                                davey.MediaType.audio,
                                raw_payload,
                            )
                            # dave.decrypt() returns raw Opus — no extension headers.
                            # The extension was already stripped by _decryptor_rtp above.
                            packet.decrypted_data = decrypted_audio
                        except Exception as exc:
                            reader_log.error("dave.decrypt failed for SSRC %s: %s", packet.ssrc, exc)
                            packet.decrypted_data = OPUS_SILENCE

                return getattr(packet, "decrypted_data", raw_payload)

            PacketDecryptor.decrypt_rtp = _patched_decrypt_rtp

            # Patch 3: PacketDecryptor._decrypt_rtp_aead_xchacha20_poly1305_rtpsize (reader.py)
            def _patched_decrypt_rtp_aead(self, packet):
                from discord.voice.receive.reader import CryptoError
                reader_log.debug(
                    "Decrypting RTP AEAD XChaCha20 Poly1305 RTPSize, has decrypted data?: %s",
                    packet.decrypted_data is not None,
                )
                packet.adjust_rtpsize()
                nonce = packet.nonce + b"\x00" * 20

                assert isinstance(self.box, nacl.secret.Aead)

                try:
                    result = self.box.decrypt(
                        packet.decrypted_data or packet.data,
                        bytes(packet.header),
                        nonce,
                    )
                except Exception as exc:
                    reader_log.error("Critical error at AEAD: %s", exc)
                    raise CryptoError(exc)

                if packet.extended:
                    packet.update_extended_header(result)

                # Pycord hardcodes 8 bytes for all packets here.
                result = result[8:]

                if getattr(packet, "padding", False) and result:
                    pad_len = result[-1]
                    if 0 < pad_len <= len(result):
                        result = result[:-pad_len]

                return result

            PacketDecryptor._decrypt_rtp_aead_xchacha20_poly1305_rtpsize = _patched_decrypt_rtp_aead

            def _patched_do_run(self):
                dave_warned = False
                while not self._end_thread.is_set():
                    self.waiter.wait()

                    with self._lock:
                        for decoder in self.waiter.items:
                            try:
                                data = decoder.pop_data()
                                if data is not None:
                                    self.sink.write(data, data.source)
                            except (OpusError, AssertionError) as exc:
                                reader_log.debug("Skipping OpusError in router: %s", exc)

            PacketRouter._do_run = _patched_do_run

            # Patch 5: PacketDecoder.pop_data (opus.py)
            # Fixes Pycord 2.8.0's JitterBuffer bug where it constantly flushes itself
            # before reaching pref_size, completely breaking packet reordering and PLC generation.
            from discord.opus import PacketDecoder
            old_pop_data = PacketDecoder.pop_data
            def _patched_pop_data(self, *, timeout: float = 0):
                # Don't pop until the jitter buffer is sufficiently full, to allow reordering
                if len(self._buffer._buffer) <= self._buffer.pref_size:
                    self._flag_ready_state()
                    return None
                
                # Now the buffer is full enough, so we can actually pop and use PLC if needed.
                packet = self._get_next_packet(timeout)
                self._flag_ready_state()

                if packet is None:
                    return None
                
                try:
                    return self._process_packet(packet)
                except Exception as exc:
                    reader_log.warning("Decoder process_packet failed: %s", exc)
                    # Return PLC silence instead of skipping
                    pcm = self._decoder.decode(None, fec=False)
                    from discord.voice.packets import VoiceData
                    return VoiceData(pcm, self._get_user(self._cached_id), packet)

            PacketDecoder.pop_data = _patched_pop_data
        except ImportError:
            log.warning("Could not patch pycord DAVE classes — voice receive may fail")

    except ImportError:
        log.warning("Could not patch discord.sinks.Sink — voice receive may fail")

    log.info("Applied pycord patches")
