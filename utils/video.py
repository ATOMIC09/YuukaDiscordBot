import asyncio
import io
import os
import tempfile
from bot.logger import logger

async def _run_ffmpeg_with_fallback(cmd_prefix: list[str], encoders: list[list[str]], out_path: str) -> str:
    """
    Runs ffmpeg by trying a list of encoder arguments in order.
    Useful for falling back from hardware encoding to software encoding.
    Returns the name of the successful encoder.
    """
    last_err = ""
    for enc_args in encoders:
        cmd = cmd_prefix + enc_args + [out_path]
        logger.debug(f"Trying FFmpeg encoder {enc_args[1]}: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode == 0:
            return enc_args[1]
            
        last_err = stderr.decode('utf-8', errors='ignore')
        logger.debug(f"FFmpeg encoder {enc_args[1]} failed, falling back...")
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
                
    logger.error(f"All FFmpeg encoders failed. Last error:\n{last_err}")
    raise RuntimeError("FFmpeg conversion failed with all encoders.")

async def merge_image_audio(image_path: str, audio_path: str, out_path: str) -> str:
    """
    Merges a static image or GIF with an audio file into an MP4 video using FFmpeg.
    Raises RuntimeError if FFmpeg fails.
    Returns the encoder used.
    """
    is_gif = image_path.lower().endswith('.gif')
    
    cmd_prefix = [
        "ffmpeg", "-y"
    ]
    
    if is_gif:
        cmd_prefix.extend(["-ignore_loop", "0"])
    else:
        cmd_prefix.extend(["-loop", "1"])
        
    cmd_prefix.extend([
        "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart"
    ])
    
    encoders = [
        ["-c:v", "h264_nvenc", "-preset", "p2"],
        ["-c:v", "h264_qsv", "-preset", "veryfast"],
        ["-c:v", "libx264", "-tune", "stillimage"]
    ]
    
    return await _run_ffmpeg_with_fallback(cmd_prefix, encoders, out_path)

async def make_deepfry_video(video_bytes: bytes) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int], str]:
    """
    Applies deepfry effects to a video (both video and audio streams).
    Returns (io.BytesIO of the mp4, extension, dummy_old_size, dummy_new_size, encoder) to match image API.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as in_f:
        in_f.write(video_bytes)
        in_path = in_f.name
        
    out_path = in_path.replace(".mp4", "_out.mp4")
    
    cmd_prefix = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-vf", "lutrgb=r='if(gt(val,127),255,0)':g='if(gt(val,127),255,0)':b='if(gt(val,127),255,0)'",
        "-af", "bass=g=15,treble=g=15,volume=8,alimiter=limit=0.9",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "32k",
        "-movflags", "+faststart"
    ]
    
    encoders = [
        ["-c:v", "h264_nvenc", "-preset", "p2", "-cq", "40", "-maxrate", "2M", "-bufsize", "4M"],
        ["-c:v", "h264_qsv", "-preset", "veryfast", "-q", "40", "-maxrate", "2M", "-bufsize", "4M"],
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "40", "-maxrate", "2M", "-bufsize", "4M"]
    ]
    
    try:
        used_encoder = await _run_ffmpeg_with_fallback(cmd_prefix, encoders, out_path)
        with open(out_path, "rb") as out_f:
            out_bytes = out_f.read()
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)
        if os.path.exists(out_path):
            os.remove(out_path)
            
    output_io = io.BytesIO(out_bytes)
    return output_io, "mp4", (0, 0), (0, 0), used_encoder
