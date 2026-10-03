import os
import tempfile
import unittest
from media_quality import download_fitting_video, fitting_formats, upload_budget


class MediaQualityTests(unittest.TestCase):
    def test_skips_large_quality_and_separate_streams(self):
        info = {"formats": [
            {"url": "high", "height": 1080, "filesize": 25000000},
            {"url": "medium", "height": 720, "filesize": 5000000},
            {"url": "silent", "height": 1080, "acodec": "none"},
            {"url": "low", "height": 480, "filesize": 2000000},
        ]}
        self.assertEqual([f["url"] for f in fitting_formats(info, 9500000)], ["medium", "low"])

    def test_bitrate_estimate(self):
        info = {"duration": 60, "formats": [
            {"url": "high", "tbr": 2000}, {"url": "low", "tbr": 500},
        ]}
        self.assertEqual([f["url"] for f in fitting_formats(info, 9500000)], ["low"])

    def test_actual_oversize_retries_lower_and_cleans_file(self):
        with tempfile.TemporaryDirectory() as folder:
            class Downloader:
                attempted = []
                def extract_info(self, url, download):
                    return {"formats": [{"url": "high", "height": 1080}, {"url": "low", "height": 480}]}
                def process_ie_result(self, info, download):
                    fmt = info["formats"][0]
                    self.attempted.append(fmt["url"])
                    path = os.path.join(folder, fmt["url"] + ".mp4")
                    with open(path, "wb") as output:
                        output.write(b"x" * (200 if fmt["url"] == "high" else 50))
                    return {"path": path}
                def prepare_filename(self, info):
                    return info["path"]
            downloader = Downloader()
            path = download_fitting_video(downloader, "video", 100)
            self.assertEqual(os.path.getsize(path), 50)
            self.assertEqual(downloader.attempted, ["high", "low"])
            self.assertFalse(os.path.exists(os.path.join(folder, "high.mp4")))

    def test_server_limit_and_configured_cap(self):
        self.assertEqual(upload_budget(9500000, 8000000), 7840000)
        self.assertEqual(upload_budget(9500000, 50000000), 9500000)


if __name__ == "__main__":
    unittest.main()
