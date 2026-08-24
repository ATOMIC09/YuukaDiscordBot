r"""Live microphone test for a trained wake-word model.

Run with wakeword_training's own venv (has onnxruntime/pyaudio):
    & wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py

Prints a live confidence meter (0-1) as you speak. Ctrl+C to stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyaudio

from livekit.wakeword import WakeWordModel

# Resolved from this script's own location, not a hardcoded machine path —
# works regardless of which machine or directory this is run from.
MODEL_PATH = Path(__file__).parent / "output" / "yuuka_wakeword_v2" / "yuuka_wakeword_v2.onnx"
SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms
CHUNK_SECONDS = 2.0
CHUNK_SAMPLES = int(CHUNK_SECONDS * SAMPLE_RATE)


def main() -> None:
    model = WakeWordModel(models=[MODEL_PATH])

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=FRAME_SAMPLES,
    )

    print("Listening... say 'Yuuka' (Ctrl+C to stop)")
    print(f"Model: {MODEL_PATH.name} -- the bot gates STT at 0.02 (see TRAINING.md).\n")

    buffer = np.zeros(0, dtype=np.int16)
    try:
        while True:
            data = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)
            buffer = np.concatenate([buffer, frame])[-CHUNK_SAMPLES:]
            if len(buffer) < CHUNK_SAMPLES:
                continue

            scores = model.predict(buffer)
            for name, score in scores.items():
                bar = "#" * int(score * 40)
                sys.stdout.write(f"\r{name}: {score:.3f} [{bar:<40}]")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
