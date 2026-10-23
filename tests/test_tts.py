"""Edge TTS wrapper: a connector per try, one retry, no temp file left behind on failure."""

import os

import pytest

from utils import tts


class FakeCommunicate:
    """Stands in for edge_tts.Communicate; `script` has one entry per save(): an exception or None."""

    script: list = []
    made: list = []

    def __init__(self, text, voice, connector=None):
        self.connector = connector
        self.path = None
        FakeCommunicate.made.append(self)

    async def save(self, path):
        self.path = path
        outcome = FakeCommunicate.script.pop(0)
        if outcome is not None:
            # What edge_tts really does: its session closes the connector it was handed.
            await self.connector.close()
            raise outcome
        with open(path, "wb") as f:
            f.write(b"mp3")


@pytest.fixture(autouse=True)
def fake_edge(monkeypatch):
    FakeCommunicate.script = []
    FakeCommunicate.made = []
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)


async def test_speaks_on_the_first_try():
    FakeCommunicate.script = [None]
    path = await tts.synthesize_speech("สวัสดีค่ะ")
    try:
        assert len(FakeCommunicate.made) == 1
        assert os.path.getsize(path) == 3
    finally:
        os.unlink(path)


async def test_retries_once_on_a_fresh_connector():
    """The 403 case: the first handshake is refused and the connector it used is closed."""
    FakeCommunicate.script = [RuntimeError("Session is closed"), None]
    path = await tts.synthesize_speech("สวัสดีค่ะ")
    try:
        first, second = FakeCommunicate.made
        assert first.connector is not second.connector
        assert first.connector.closed and second.connector.closed
        assert os.path.getsize(path) == 3
    finally:
        os.unlink(path)


async def test_gives_up_after_the_retry_and_leaves_no_file():
    FakeCommunicate.script = [RuntimeError("one"), RuntimeError("two")]
    with pytest.raises(RuntimeError, match="two"):
        await tts.synthesize_speech("สวัสดีค่ะ")
    assert len(FakeCommunicate.made) == 2
    assert not os.path.exists(FakeCommunicate.made[0].path)
