import moviepy.editor as mp

def mix(video_url, audio_url, output_filename):
    video = mp.VideoFileClip(video_url)
    audio = mp.AudioFileClip(audio_url)
    video_with_audio = video.set_audio(audio)
    video_with_audio.write_videofile(f'temp/{output_filename}.mp4', codec='libx264')
