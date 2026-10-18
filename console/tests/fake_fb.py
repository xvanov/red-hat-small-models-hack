"""Stand-in for the Facebook Page calls (CONSOLE_FB_MODULE=console.tests.fake_fb). Nothing leaves the machine."""
import itertools

_IDS = itertools.count(1)
POSTS: dict[str, dict] = {}


def create_unpublished_post(text):
    pid = f"fake_{next(_IDS)}"
    POSTS[pid] = {"text": text, "is_published": False}
    return {"post_id": pid, "photo_id": None, "is_published": False}


def publish(text):
    import time
    time.sleep(0.5)  # a real publish takes seconds: wide enough for a double click to overlap
    pid = f"fake_{next(_IDS)}"
    POSTS[pid] = {"text": text, "is_published": True}
    return {"post_id": pid, "is_published": True, "permalink_url": f"https://example.invalid/posts/{pid}"}


def delete(post_id):
    POSTS.pop(post_id, None)
    return {"post_id": post_id, "success": True}
