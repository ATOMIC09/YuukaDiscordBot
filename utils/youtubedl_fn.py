import yt_dlp
from utils import filesize

def get_video_info(url):
    video_info = {}
    ydl_opts = {'format': 'best'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    video_info['original_url'] = info['original_url']
    video_info['title'] = info['title']
    video_info['ext'] = info['ext']
    video_info['upload_date'] = info['upload_date']
    video_info['channel_id'] = info['channel_id']
    video_info['channel_follower_count'] = info['channel_follower_count']
    video_info['uploader'] = info['uploader']
    video_info['uploader_id'] = info['uploader_id']
    video_info['duration'] = info['duration']
    video_info['view_count'] = info['view_count']
    video_info['like_count'] = info['like_count']
    video_info['comment_count'] = info['comment_count']
    video_info['filesize_approx'] = filesize.prefix(info['filesize_approx'])
    thumbnail_dict = info['thumbnails']
    thumbnail = thumbnail_dict[len(thumbnail_dict)-1]['url']
    video_info['thumbnail'] = thumbnail
    video_info['resolution'] = info['resolution']
    video_info['fps'] = info['fps']
    print(video_info)
    return video_info

def get_video_url(url):
    ydl_opts = {'format': 'best'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info['url']

def get_audio_url(url):
    ydl_opts = {'format': 'bestaudio', 'noplaylist': 'True'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info['url']

# Get audio clip name
def yt_audio_get_clip_name(url):
    YDL_OPTIONS = {'format': 'bestaudio[ext=m4a]', 'noplaylist': 'True', 'outtmpl': '%(title)s.%(ext)s'}
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)
    return filename

# Get video clip name
def yt_video_get_clip_name(url):
    YDL_OPTIONS = {'format': 'best', 'outtmpl': '%(title)s.%(ext)s'}
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        filename = ydl.prepare_filename(info)
    return filename

# Download audio into a directory
def yt_audio_dir(url):
    YDL_OPTIONS = {'format': 'bestaudio[ext=m4a]', 'noplaylist': 'True', 'outtmpl': 'temp/audio/%(title)s.%(ext)s'}
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)

# Download video into a directory
def yt_video_dir_best(url):
    VIDEO_YDL_OPTIONS = {'format': 'best', 'outtmpl': 'temp/video/%(title)s.%(ext)s'}
    with yt_dlp.YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)

def yt_video_dir_worst(url):
    VIDEO_YDL_OPTIONS = {'format': 'worst', 'outtmpl': 'temp/video/%(title)s.%(ext)s'}
    with yt_dlp.YoutubeDL(VIDEO_YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=True)


if __name__ == '__main__':
    url = 'https://www.youtube.com/watch?v=f8mL0_4GeV0'
    info = get_video_info(url)
    print(get_video_url(url))
    print(get_audio_url(url))