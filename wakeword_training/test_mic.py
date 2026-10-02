r"""Live microphone test for a trained wake-word model.

Run with wakeword_training's own venv (has onnxruntime/pyaudio), from the repo root:
    wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py
    wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py --model <path/to/model.onnx>
    wakeword_training\.venv\Scripts\python.exe wakeword_training\test_mic.py --list-devices

Scores the last 2 s of audio every 80 ms, which is how openWakeWord streams and how
utils/wake_acoustic.py scores a segment: the classifier only fires when the word sits at
the trailing edge of its window, so it has to be asked at every hop. Prints a live meter,
the peak of the last few seconds, and a WAKE line whenever the score crosses the
threshold. Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudio

from livekit.wakeword import WakeWordModel

# Resolved from this script's own location, not a hardcoded machine path —
# works regardless of which machine or directory this is run from.
DEFAULT_MODEL = Path(__file__).parent / "output" / "yuuka_wakeword_v3" / "yuuka_wakeword_v3.onnx"
SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms
CHUNK_SAMPLES = 2 * SAMPLE_RATE
PEAK_HOLD_FRAMES = 38  # ~3 s of 80 ms hops


def list_devices(pa: pyaudio.PyAudio) -> None:
    default = pa.get_default_input_device_info()["index"]
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            mark = "  (default)" if i == default else ""
            print(f"{i:3d}  {info['name']}{mark}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--cooldown", type=float, default=1.5, help="Seconds between WAKE lines.")
    parser.add_argument("--device", type=int, help="Input device index (see --list-devices).")
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    if args.list_devices:
        list_devices(pa)
        pa.terminate()
        return 0
    if not args.model.is_file():
        parser.error(f"Model not found: {args.model}")

    model = WakeWordModel(models=[args.model])
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=args.device,
        frames_per_buffer=FRAME_SAMPLES,
    )

    print(f"Model: {args.model.name}  threshold: {args.threshold:.2f}")
    print("Speak 'Yuuka' (Ctrl+C to stop)\n")

    buffer = np.zeros(0, dtype=np.int16)
    recent: deque[float] = deque(maxlen=PEAK_HOLD_FRAMES)
    wakes = 0
    last_wake = float("-inf")
    try:
        while True:
            data = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)
            buffer = np.concatenate([buffer, frame])[-CHUNK_SAMPLES:]
            if len(buffer) < CHUNK_SAMPLES:
                continue

            score = max(model.predict(buffer).values())
            recent.append(score)
            level = int(np.abs(frame).max()) / 32768
            now = time.monotonic()
            if score >= args.threshold and now - last_wake >= args.cooldown:
                wakes += 1
                last_wake = now
                sys.stdout.write(f"\r[{datetime.now():%H:%M:%S}] WAKE #{wakes} score={score:.3f}{' ' * 40}\n")
            bar = "#" * int(score * 30)
            sys.stdout.write(
                f"\rscore {score:.3f} [{bar:<30}] peak {max(recent):.3f} | mic {level:.2f} | wakes {wakes}  "
            )
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
