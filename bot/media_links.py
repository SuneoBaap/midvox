"""Only explicit Shorts and Reels URLs enter the media downloader."""

import re

INSTA_URL_RE = re.compile(
    r"(?<![\w./-])(?:https?://)?(?:www\.|m\.|dl\.)?"
    r"(?:instagram\.com|instagr\.am)/(?:reel|reels)/([\w-]+)",
    re.IGNORECASE,
)
YT_SHORTS_URL_RE = re.compile(
    r"(?<![\w./-])(?:https?://)?(?:www\.|m\.)?"
    r"youtube\.com/shorts/([\w-]{11})(?![\w-])",
    re.IGNORECASE,
)


def short_media_link(content):
    matches = [(match.start(), source, match) for source, pattern in (
        ("instagram", INSTA_URL_RE), ("youtube", YT_SHORTS_URL_RE),
    ) if (match := pattern.search(content))]
    if not matches:
        return None
    _, source, match = min(matches, key=lambda entry: entry[0])
    url = (f"https://www.youtube.com/shorts/{match[1]}" if source == "youtube"
           else f"https://www.instagram.com/reel/{match[1]}/")
    return source, url, match[1]
