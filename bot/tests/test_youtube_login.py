import ast
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[2] / "docker/youtube_login_server.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
function = next(node for node in tree.body if getattr(node, "name", "") == "youtube_cookie_header")
restore_function = next(node for node in tree.body if getattr(node, "name", "") == "youtube_browser_cookies")
namespace = {}
exec(compile(ast.Module(body=[function, restore_function], type_ignores=[]), str(source), "exec"), namespace)
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

    def test_browser_restore_keeps_cookie_values_and_restricts_domain(self):
        cookies = namespace["youtube_browser_cookies"]({"youtube": ["SID=session==; PREF=value"]})
        self.assertEqual(cookies[0]["value"], "session==")
        self.assertTrue(all(c["domain"] == ".youtube.com" and c["secure"] for c in cookies))

    def test_missing_or_malformed_session_restores_no_cookies(self):
        for contents in ({}, {"youtube": []}, {"youtube": "invalid"}, {"youtube": [None]}):
            self.assertEqual(namespace["youtube_browser_cookies"](contents), [])
