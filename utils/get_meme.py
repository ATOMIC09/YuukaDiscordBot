import asyncpraw
import os

async def get_reddit():
    reddit = asyncpraw.Reddit(
        client_id=os.environ['client_id'],
        client_secret=os.environ['client_secret'],
        user_agent='GetVideoFromReddit',
    )

    subreddit = await reddit.subreddit('perfectlycutscreams')
    random_submission = await subreddit.random()

    if random_submission.is_video:
        video_name = random_submission.title
        video_url = random_submission.media['reddit_video']['fallback_url']
        replacenum = video_url.split('DASH_')[1].split('.mp4')[0]
        audio_url = video_url.replace(replacenum, 'audio')
        post_link = f"https://www.reddit.com{random_submission.permalink}"
        return video_url, audio_url, video_name, post_link