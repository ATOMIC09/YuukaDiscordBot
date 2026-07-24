import asyncio
from bot.logger import logger

async def merge_image_audio(image_path: str, audio_path: str, out_path: str) -> None:
    """
    Merges a static image or GIF with an audio file into an MP4 video using FFmpeg.
    Raises RuntimeError if FFmpeg fails.
    """
    is_gif = image_path.lower().endswith('.gif')
    
    cmd = [
        "ffmpeg",
        "-y", # Overwrite output if exists
    ]
    
    if is_gif:
        cmd.extend(["-ignore_loop", "0"])
    else:
        cmd.extend(["-loop", "1"])
        
    cmd.extend([
        "-i", image_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        # Ensure dimensions are even numbers (required by libx264)
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        out_path
    ])
    
    logger.debug(f"Running FFmpeg: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        err = stderr.decode('utf-8', errors='ignore')
        logger.error(f"FFmpeg failed with code {process.returncode}:\n{err}")
        raise RuntimeError("FFmpeg conversion failed.")
