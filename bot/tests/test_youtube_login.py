import ast
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[2] / "docker/youtube_login_server.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
function = next(node for node in tree.body if getattr(node, "name", "") == "youtube_cookie_header")
namespace = {}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
cookie_header = namespace["youtube_cookie_header"]


class YouTubeLoginTests(unittest.TestCase):
    def test_only_youtube_cookies_saved(self):
        cookies = [{"name": "SID", "value": "session", "domain": ".youtube.com"},
                   {"name": "PREF", "value": "preferences", "domain": "www.youtube.com"},
                   {"name": "OTHER", "value": "secret", "domain": ".google.com"},
                   {"name": "OTHER", "value": "secret", "domain": "evilyoutube.com"}]
        self.assertEqual(cookie_header(cookies), "SID=session; PREF=preferences")

    def test_anonymous_session_cannot_be_saved_as_login(self):
        with self.assertRaisesRegex(ValueError, "Finish signing in"):
            cookie_header([{"name": "PREF", "value": "x", "domain": ".youtube.com"}])
