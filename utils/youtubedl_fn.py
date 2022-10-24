from asyncio import subprocess
from youtube_dl import YoutubeDL

VIDEO_YDL_OPTIONS = {'format': 'best'}

def yt_title(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_NAME = info['title']
    return VIDEO_NAME

def yt_ext(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_EXT = info['ext']
    return VIDEO_EXT

def yt_upload_date(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_UPLOAD_DATE = info['upload_date']
    return VIDEO_UPLOAD_DATE

def yt_channel(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_CHANNEL = info['channel']
    CHANNEL_ID = info['channel_id']
    return VIDEO_CHANNEL, CHANNEL_ID

def yt_duration(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_DURATION = info['duration']
    return VIDEO_DURATION

def yt_view_count(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_VIEW_COUNT = info['view_count']
    return VIDEO_VIEW_COUNT

def yt_like_count(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_LIKE_COUNT = info['like_count']
    return VIDEO_LIKE_COUNT

def yt_dislike_count(url):
    try:
        with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
        VIDEO_DISLIKE_COUNT = info['dislike_count']
        return VIDEO_DISLIKE_COUNT
    except:
        return "-"

def yt_comment_count(url):
    try:
        with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
        VIDEO_COMMENT_COUNT = info['comment_count']
        return VIDEO_COMMENT_COUNT
    except:
        return "-"

def yt_filesize_approx(url):
    try:
        with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
        VIDEO_FILESIZE_APPROX = info['filesize_approx']
        return VIDEO_FILESIZE_APPROX
    except:
        return "-"

def yt_thumbnail(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    thumbnail_dict = info['thumbnails']
    thumbnail = thumbnail_dict[len(thumbnail_dict)-1]['url']
    return thumbnail
    
def yt_video(url):
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    VIDEO_URL = info['url']
    return VIDEO_URL

def yt_audio(url):
    AUDIO_YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True'}

    with YoutubeDL(AUDIO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
    AUDIO_DOWNLOAD = info['url']
    return AUDIO_DOWNLOAD

# Get audio clip name
def yt_audio_get_clip_name(url):
    YDL_OPTIONS = {'format': 'bestaudio[ext=m4a]', 'noplaylist': 'True', 'outtmpl': '%(title)s.%(ext)s'}
    with YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)
    return filename

# Get video clip name
def yt_video_get_clip_name(url):
    YDL_OPTIONS = {'format': 'best', 'outtmpl': '%(title)s.%(ext)s'}
    with YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)
    return filename

# Download audio into a directory
def yt_audio_dir(url):
    YDL_OPTIONS = {'format': 'bestaudio[ext=m4a]', 'noplaylist': 'True', 'outtmpl': 'temp/audio/%(title)s.%(ext)s'}
    with YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)

# Download video into a directory
def yt_video_dir_best(url):
    VIDEO_YDL_OPTIONS = {'format': 'best', 'outtmpl': 'temp/video/%(title)s.%(ext)s'}
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)

def yt_video_dir_worst(url):
    VIDEO_YDL_OPTIONS = {'format': 'worst', 'outtmpl': 'temp/video/%(title)s.%(ext)s'}
    with YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)
