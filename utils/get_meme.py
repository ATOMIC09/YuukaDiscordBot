import asyncpraw
import os
import random

async def get_reddit():
    reddit = asyncpraw.Reddit(
        client_id=os.environ['client_id'],
        client_secret=os.environ['client_secret'],
        user_agent='GetVideoFromReddit',
    )

    try:
        # List of subreddit names
        subreddit_names = ['shitposting', 'perfectlycutscreams', 'cursed_videomemes']
        random_subreddit_name = random.choice(subreddit_names)
        
        subreddit = await reddit.subreddit(random_subreddit_name)
        random_submission = await subreddit.random()

        if random_submission.is_video:
            video_name = random_submission.title
            for i in range(len(video_name)):
                if video_name[i] in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                    video_name = video_name.replace(video_name[i], '')
            video_url = random_submission.media['reddit_video']['fallback_url']
            replacenum = video_url.split('DASH_')[1].split('.mp4')[0]
            audio_url = video_url.replace(replacenum, 'audio')
            post_link = f"https://www.reddit.com{random_submission.permalink}"
            return video_url, audio_url, video_name, post_link
    except:
        return None
    finally:
        await reddit.close()