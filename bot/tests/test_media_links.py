import unittest
from media_links import short_media_link


class MediaLinkTests(unittest.TestCase):
    def test_shorts_and_reels(self):
        self.assertEqual(short_media_link("https://m.youtube.com/shorts/73ibzRVY7xQ?si=tracking"),
                         ("youtube", "https://www.youtube.com/shorts/73ibzRVY7xQ", "73ibzRVY7xQ"))
        self.assertEqual(short_media_link("instagram.com/reels/Ab_c-123/?igsh=abc"),
                         ("instagram", "https://www.instagram.com/reel/Ab_c-123/", "Ab_c-123"))

    def test_regular_videos_images_stories_and_shared_links_are_ignored(self):
        for url in ("https://youtube.com/watch?v=73ibzRVY7xQ", "https://youtu.be/73ibzRVY7xQ",
                    "https://instagram.com/p/test/", "https://instagram.com/tv/test/",
                    "https://instagram.com/stories/person/123", "https://instagram.com/share/test",
                    "https://evil.com/youtube.com/shorts/73ibzRVY7xQ",
                    "https://evilyoutube.com/shorts/73ibzRVY7xQ"):
            with self.subTest(url=url):
                self.assertIsNone(short_media_link(url))

    def test_first_supported_link_and_canonical_identity(self):
        self.assertEqual(short_media_link("youtube.com/shorts/73ibzRVY7xQ instagram.com/reel/test")[0], "youtube")
        self.assertEqual(short_media_link("https://www.instagram.com/reel/test/?a=1"),
                         short_media_link("https://instagram.com/reels/test/?a=2"))
