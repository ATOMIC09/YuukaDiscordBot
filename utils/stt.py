"""
utils/stt.py
Core Speech-to-Text inference engine using Typhoon ASR Real-Time.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Disable tqdm globally before any heavy libraries import it
os.environ["TQDM_DISABLE"] = "1"

from bot.logger import logger

_model_loaded: bool = False
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
_asr_model = None
_device: str = "cpu"

# Opus decoder output constants (pycord hardcoded values)
_OPUS_CHANNELS = 2
_OPUS_SAMPLE_WIDTH = 2
_OPUS_SAMPLE_RATE = 48_000


def _pcm_to_wav(pcm_bytes: bytes) -> io.BytesIO:
    """Wrap raw PCM bytes in a proper WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_OPUS_CHANNELS)
        wf.setsampwidth(_OPUS_SAMPLE_WIDTH)
        wf.setframerate(_OPUS_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    return buf


def load_model(device: str | None = None) -> None:
    """Load the Typhoon ASR model once into memory."""
    global _model_loaded, _asr_model, _device

    if _model_loaded:
        return

    try:
        import torch
        if device is None:
            if torch.cuda.is_available():
                _device = "cuda"
                logger.info("CUDA is available! Using GPU for Typhoon ASR.")
            else:
                _device = "cpu"
                logger.info("CUDA is not available. Using CPU for Typhoon ASR.")
        else:
            _device = device
            logger.info(f"Loading Typhoon ASR model on {_device.upper()}...")
    except ImportError:
        _device = "cpu" if device is None else device
        logger.info(f"Loading Typhoon ASR model on {_device.upper()}...")

    try:
        import logging
        try:
            from nemo.utils import logging as nemo_logging
            nemo_logger = logging.getLogger("nemo_logger")
            nemo_logger.handlers = []
            nemo_logger.propagate = True
            nemo_logger.setLevel(logging.ERROR)
        except ImportError:
            pass

        import nemo.collections.asr as nemo_asr

        # Explicitly silence noisy Lhotse and NeMo dataloader loggers
        noisy_loggers = [
            "nemo.collections.common.data.lhotse.dataloader",
            "nemo.collections.common.data.lhotse.cutset",
            "nemo_logger",
            "nemo",
            "nv_one_logger",
        ]
        for name in noisy_loggers:
            l = logging.getLogger(name)
            l.setLevel(logging.ERROR)

        for logger_name in list(logging.root.manager.loggerDict.keys()):
            if any(prefix in logger_name for prefix in ("nemo", "lightning", "pytorch_lightning", "lhotse")):
                l = logging.getLogger(logger_name)
                l.setLevel(logging.ERROR)

        _asr_model = nemo_asr.models.ASRModel.from_pretrained(
            model_name="scb10x/typhoon-asr-realtime",
            map_location=_device
        )
        
        _model_loaded = True
        logger.info("Typhoon ASR ready")
    except ImportError:
        logger.error(
            "nemo_toolkit is not installed or failed to import.\n"
            "STT transcription will be disabled."
        )


def _prepare_audio(wav_path: str, target_sr: int = 16000) -> str:
    """Resample audio using librosa and save to a new temporary file."""
    import librosa
    import soundfile as sf
    
    y, sr = librosa.load(wav_path, sr=None)
    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    
    y = y / (max(abs(y)) + 1e-8)
    
    processed_path = str(Path(wav_path).with_suffix('.16k.wav'))
    sf.write(processed_path, y, target_sr)
    return processed_path


def _run_transcribe(wav_path: str) -> str:
    """Blocking transcription call."""
    if _asr_model is None:
        return ""
        
    processed_path = ""
    try:
        processed_path = _prepare_audio(wav_path, target_sr=16000)
        
        # Suppress NeMo loggers that get dynamically reset
        import logging
        noisy = [
            "nemo.collections.common.data.lhotse.dataloader",
            "nemo.collections.common.data.lhotse.cutset",
            "nemo_logger",
            "nv_one_logger",
        ]
        for name in noisy:
            logging.getLogger(name).setLevel(logging.ERROR)

        # Suppress any extra stdout during transcribe since NeMo can be noisy
        original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
        try:
            transcriptions = _asr_model.transcribe(audio=[processed_path])
        finally:
            sys.stdout.close()
            sys.stdout = original_stdout
            
        if transcriptions and len(transcriptions) > 0:
            text_val = transcriptions[0]
            if hasattr(text_val, "text"):
                text_val = text_val.text
            return str(text_val).strip()
        return ""
    except Exception as exc:
        logger.error(f"STT transcription error: {exc}")
        return ""
    finally:
        if processed_path and os.path.exists(processed_path):
            try:
                os.unlink(processed_path)
            except OSError:
                pass


async def transcribe_wav_bytes(wav_bytes: io.BytesIO, user_display: str) -> str:
    """Transcribe audio from a BytesIO WAV file asynchronously."""
    if not _model_loaded:
        logger.warning("STT model not loaded — skipping transcription for %s", user_display)
        return ""

    loop = asyncio.get_running_loop()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes.read())
        tmp_path = tmp.name

    transcript = await loop.run_in_executor(_executor, _run_transcribe, tmp_path)

    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    if transcript:
        logger.info(f"[STT] {user_display}: {transcript}")
    else:
        logger.debug(f"[STT] {user_display}: (no speech detected)")

    return transcript
