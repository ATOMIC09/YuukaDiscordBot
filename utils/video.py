import moviepy.editor as mp
import requests

def check_http_status(url):
    try:
        response = requests.head(url)
        return response.status_code
    except requests.RequestException as e:
        print(f"Request exception occurred: {e}")
        return None

def mix(video_url, audio_url, output_filename):
    video_http_status = check_http_status(video_url)
    audio_http_status = check_http_status(audio_url)
    print(f"Video URL returned status code: {video_http_status}")
    print(f"Audio URL returned status code: {audio_http_status}")

    if video_http_status!= 200:
        return f"Video URL returned status code: {video_http_status}"
    if audio_http_status != 200:
        return f"Audio URL returned status code: {audio_http_status}"

    try:
        video = mp.VideoFileClip(video_url)
        audio = mp.AudioFileClip(audio_url)
        video_with_audio = video.set_audio(audio)
        video_with_audio.write_videofile(f'temp/video/{output_filename}.mp4', codec='libx264')
    except Exception as e:
        print(f"An error occurred while processing video and audio: {e}")
        return "An error occurred while processing video and audio"

    return 'Success'

def download_video_only(video_url, output_filename):
    video_http_status = check_http_status(video_url)
    print(f"Video URL returned status code: {video_http_status}")

    if video_http_status != 200:
        return f"Video URL returned status code: {video_http_status}"

    try:
        video = mp.VideoFileClip(video_url)
        video.write_videofile(f'temp/video/{output_filename}.mp4', codec='libx264')
    except Exception as e:
        print(f"An error occurred while processing the video: {e}")
        return "An error occurred while processing the video"

    return 'Success'