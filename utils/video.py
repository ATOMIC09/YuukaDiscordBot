import asyncio
import io
import os
import re
import tempfile
from bot.logger import logger

# Fallback when no guild context is available (e.g. DMs) or the limit can't be determined.
# This matches Discord's base (non-boosted, Boost Level 0/1) per-file limit of 10MB.
DISCORD_UPLOAD_LIMIT = 10 * 1024 * 1024
_MIN_VIDEO_BITRATE_KBPS = 100
_MIN_AUDIO_BITRATE_KBPS = 32
# Used only if every duration-detection strategy fails. Deliberately pessimistic (long):
# underestimating duration makes the bitrate target too high and overshoots the size limit,
# while overestimating it just compresses harder than strictly necessary. Overshooting is
# the failure mode that actually breaks the command, so we bias toward the safe side.
_FALLBACK_DURATION_SEC = 600.0

async def _probe_duration(path: str, entries: str, select_stream: str | None = None) -> float:
    cmd = ["ffprobe", "-v", "error"]
    if select_stream:
        cmd += ["-select_streams", select_stream]
    cmd += ["-show_entries", entries, "-of", "default=noprint_wrapped_values=1:nokey=1", path]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    try:
        # Some containers report duration on every stream line; take the first valid one.
        for line in stdout.decode().strip().splitlines():
            return float(line)
    except ValueError:
        pass
    return 0.0

async def _get_video_resolution(path: str) -> tuple[int, int]:
    """
    Returns (width, height) of a video's first video stream, or (0, 0) if it can't be read.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        path
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    try:
        width_str, height_str = stdout.decode().strip().split("x")
        return int(width_str), int(height_str)
    except (ValueError, IndexError):
        return (0, 0)

async def _get_video_duration(path: str) -> float:
    """
    Returns the duration of a video file in seconds, trying several strategies.
    Some containers (fragmented/streamed mp4, certain mobile recordings re-muxed by
    Discord) don't populate the top-level format duration tag, which previously caused
    duration to silently read as 0 and fall back to an optimistic guess - underestimating
    a video's real length makes the bitrate target too high and the output overshoots the
    upload limit. Returns 0.0 only if every strategy below fails.
    """
    # 1) Container-level duration - works for most well-formed files.
    duration = await _probe_duration(path, "format=duration")
    if duration > 0:
        return duration

    # 2) Video stream duration - some containers only tag the stream, not the format.
    duration = await _probe_duration(path, "stream=duration", select_stream="v:0")
    if duration > 0:
        return duration

    # 3) Last resort: ffmpeg prints "Duration: HH:MM:SS.ss" to stderr while probing headers,
    # and can often infer it even when ffprobe's structured queries come up empty.
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr.decode("utf-8", errors="ignore"))
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    return 0.0

def _calc_bitrates_kbps(duration_sec: float, target_bytes: int) -> tuple[int, int]:
    """
    Given a video's duration and a target output size, returns (video_kbps, audio_kbps)
    such that the encoded file should land at/under target_bytes regardless of duration.
    """
    # Leave 8% headroom below the target to absorb container/muxing overhead and encoder overshoot.
    target_total_kbps = (target_bytes * 8 / 1000) * 0.92 / duration_sec

    audio_kbps = _MIN_AUDIO_BITRATE_KBPS
    video_kbps = target_total_kbps - audio_kbps
    if video_kbps < _MIN_VIDEO_BITRATE_KBPS:
        # Very long video: shrink audio bitrate too rather than letting video go unreasonably low.
        audio_kbps = max(8, target_total_kbps * 0.15)
        video_kbps = max(_MIN_VIDEO_BITRATE_KBPS, target_total_kbps - audio_kbps)

    return int(video_kbps), int(audio_kbps)

def _calc_audio_kbps_for_image_track(duration_sec: float, target_bytes: int, video_kbps: float = 0) -> int:
    """
    Budgets audio bitrate to fit target_bytes over duration_sec, after reserving
    `video_kbps` (0 for a plain static image, since it costs almost nothing beyond
    the first keyframe).
    """
    target_total_kbps = (target_bytes * 8 / 1000) * 0.92 / duration_sec
    return int(max(24, target_total_kbps - video_kbps))

def _calc_bitrates_for_gif_kbps(duration_sec: float, target_bytes: int) -> tuple[int, int]:
    """
    A GIF track has real per-frame motion (unlike a plain static image), so it needs its
    own bitrate reservation to avoid runaway size on long/busy GIFs. Audio is capped at a
    sane ceiling first (AAC doesn't need much more than this to sound good) and video gets
    whatever's left, since video is the actual visual content here and was measured to be
    bit-starved when audio was allowed to take the majority of the budget (SSIM 0.93 -> 0.98
    just from reallocating, at the same total output size).
    """
    target_total_kbps = (target_bytes * 8 / 1000) * 0.92 / duration_sec
    audio_kbps = max(64, min(128, target_total_kbps * 0.25))
    video_kbps = max(150, target_total_kbps - audio_kbps)
    return int(video_kbps), int(audio_kbps)

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

async def merge_image_audio(image_path: str, audio_path: str, out_path: str, upload_limit: int = DISCORD_UPLOAD_LIMIT) -> str:
    """
    Merges a static image or GIF with an audio file into an MP4 video using FFmpeg.
    Output length follows the audio, so a long (even if small) audio file can still
    produce an oversized output if bitrate isn't bounded - bitrate is targeted from the
    audio's duration to land under `upload_limit` regardless of length.
    Raises RuntimeError if FFmpeg fails.
    Returns the encoder used.
    """
    is_gif = image_path.lower().endswith('.gif')

    duration = await _get_video_duration(audio_path)
    if duration <= 0:
        duration = _FALLBACK_DURATION_SEC

    target_bytes = upload_limit
    used_encoder = ""

    # Up to 4 attempts: shrink the target and re-encode if it still overshoots the limit.
    for attempt in range(4):
        cmd_prefix = ["ffmpeg", "-y"]

        if is_gif:
            # A GIF actually changes frame-to-frame, so it gets its own bitrate reservation.
            # libx264-only (not nvenc/qsv): measured nvenc overshooting its own -maxrate by
            # ~36% at the same requested bitrate, which fed back into the retry loop as a
            # worse-than-real overshoot and crushed quality further on the next attempt.
            # libx264 landed almost exactly on the requested bitrate and scored higher SSIM
            # for the same bits, so it's the more predictable and better-quality choice here -
            # GPU speed isn't a meaningful factor for a short looping clip either way.
            # Uses CRF (quality-adaptive) with -maxrate/-bufsize only as a ceiling, rather
            # than forcing -b:v as a flat target: measured CRF+ceiling scoring a higher SSIM
            # than an equivalent forced bitrate (0.946 vs 0.923), since it only spends up to
            # the cap on content that's actually complex enough to need it instead of forcing
            # every GIF - simple or busy - to consume the exact same bits.
            video_kbps, audio_kbps = _calc_bitrates_for_gif_kbps(duration, target_bytes)
            cmd_prefix.extend(["-ignore_loop", "0"])
            encoders = [
                ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", f"{video_kbps}k", "-bufsize", f"{int(video_kbps * 2)}k"]
            ]
        else:
            # A plain static image only costs real bits on its first keyframe - everything
            # after should be near-free since the frame never changes. But nvenc/qsv still
            # insert a full-quality keyframe every ~10s by default (their GOP default), and
            # measured (not assumed) that this alone made a 3-minute clip balloon to ~27MB
            # even at the lowest audio bitrate. h264_nvenc also doesn't respect a large -g /
            # -no-scenecut the way libx264 does (it got *worse*, not better) - only libx264
            # reliably collapses to near-zero video bitrate for unchanging content, so that's
            # the only encoder used here; GPU speed isn't a meaningful factor for one frame.
            audio_kbps = _calc_audio_kbps_for_image_track(duration, target_bytes)
            cmd_prefix.extend(["-loop", "1"])
            encoders = [
                ["-c:v", "libx264", "-tune", "stillimage", "-g", "999999", "-x264-params", "scenecut=0"]
            ]

        cmd_prefix.extend([
            "-i", image_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a", "aac",
            "-b:a", f"{audio_kbps}k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-movflags", "+faststart"
        ])

        used_encoder = await _run_ffmpeg_with_fallback(cmd_prefix, encoders, out_path)
        out_size = os.path.getsize(out_path)

        if out_size <= upload_limit:
            break

        logger.debug(f"merge_image_audio output ({out_size} bytes) exceeded limit ({upload_limit} bytes) on attempt {attempt + 1}, retrying with a lower target.")
        target_bytes = int(target_bytes * (upload_limit / out_size) * 0.90)

    return used_encoder

async def make_deepfry_video(video_bytes: bytes, upload_limit: int = DISCORD_UPLOAD_LIMIT) -> tuple[io.BytesIO, str, tuple[int, int], tuple[int, int], str]:
    """
    Applies deepfry effects to a video (both video and audio streams).
    The deepfry filter (hard RGB thresholding) produces very high-entropy, noisy-looking
    frames that are expensive to compress, so the output is bitrate-targeted from the
    source duration to reliably land under `upload_limit` regardless of video length.

    `upload_limit` should be the caller's actual destination limit (e.g. the target
    guild's boost-tier filesize_limit, which can be as low as 10MB) rather than a flat
    constant, since sending a file bigger than that limit is rejected by Discord outright.
    Returns (io.BytesIO of the mp4, extension, old_resolution, new_resolution, encoder) to
    match the image API's signature; old/new resolution are identical since this filter
    doesn't rescale the frame.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as in_f:
        in_f.write(video_bytes)
        in_path = in_f.name

    out_path = in_path.replace(".mp4", "_out.mp4")

    duration = await _get_video_duration(in_path)
    if duration <= 0:
        duration = _FALLBACK_DURATION_SEC  # unknown duration: assume the long/pessimistic case

    target_bytes = upload_limit
    used_encoder = ""

    try:
        # Up to 4 attempts: if an encode still overshoots the limit (e.g. encoder bitrate
        # overshoot on very noisy content), shrink the target and re-encode. The extra 10%
        # cut (beyond the measured overshoot ratio) ensures each retry actually clears the
        # limit instead of asymptotically approaching it from above.
        for attempt in range(4):
            video_kbps, audio_kbps = _calc_bitrates_kbps(duration, target_bytes)
            maxrate_kbps = int(video_kbps * 1.5)
            bufsize_kbps = int(video_kbps * 2)

            cmd_prefix = [
                "ffmpeg", "-y",
                "-i", in_path,
                "-vf", "lutrgb=r='if(gt(val,127),255,0)':g='if(gt(val,127),255,0)':b='if(gt(val,127),255,0)'",
                "-af", "bass=g=15,treble=g=15,volume=8,alimiter=limit=0.9",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", f"{audio_kbps}k",
                "-movflags", "+faststart"
            ]

            encoders = [
                ["-c:v", "h264_nvenc", "-preset", "p2", "-b:v", f"{video_kbps}k", "-maxrate", f"{maxrate_kbps}k", "-bufsize", f"{bufsize_kbps}k"],
                ["-c:v", "h264_qsv", "-preset", "veryfast", "-b:v", f"{video_kbps}k", "-maxrate", f"{maxrate_kbps}k", "-bufsize", f"{bufsize_kbps}k"],
                ["-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{video_kbps}k", "-maxrate", f"{maxrate_kbps}k", "-bufsize", f"{bufsize_kbps}k"]
            ]

            used_encoder = await _run_ffmpeg_with_fallback(cmd_prefix, encoders, out_path)
            out_size = os.path.getsize(out_path)

            if out_size <= upload_limit:
                break

            logger.debug(f"Deepfry output ({out_size} bytes) exceeded limit ({upload_limit} bytes) on attempt {attempt + 1}, retrying with a lower target.")
            target_bytes = int(target_bytes * (upload_limit / out_size) * 0.90)

        # The deepfry filter only thresholds RGB values, it never rescales - so resolution
        # is unchanged from source to output.
        resolution = await _get_video_resolution(out_path)

        with open(out_path, "rb") as out_f:
            out_bytes = out_f.read()
    finally:
        if os.path.exists(in_path):
            os.remove(in_path)
        if os.path.exists(out_path):
            os.remove(out_path)

    output_io = io.BytesIO(out_bytes)
    return output_io, "mp4", resolution, resolution, used_encoder
