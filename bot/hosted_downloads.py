"""Bounded hosted Cobalt downloads, with provider failover and media checks."""

import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class HostedDownloads:
    def __init__(self):
        self.cooldowns = {}

    def providers(self):
        # Use only endpoints explicitly configured by the owner. Public
        # instance lists do not promise availability or automated API access.
        try:
            entries = json.loads(os.getenv("COBALT_HOSTED_PROVIDERS", "[]"))
            if not isinstance(entries, list):
                raise ValueError
            result = []
            for index, entry in enumerate(entries[:3]):
                if not isinstance(entry, dict):
                    raise ValueError
                endpoint = entry.get("url", "").strip().rstrip("/")
                parsed = urllib.parse.urlsplit(endpoint)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                    raise ValueError
                result.append((index, endpoint, entry.get("api_key", "")))
            return result
        except (ValueError, TypeError, AttributeError):
            print("[InstaDL] invalid COBALT_HOSTED_PROVIDERS configuration")
            return []

    def download(self, url, limit):
        deadline = time.monotonic() + 90
        for index, endpoint, key in self.providers():
            if self.cooldowns.get(endpoint, 0) > time.monotonic():
                continue
            try:
                for quality in ("max", "1080", "720", "480", "360", "240"):
                    if time.monotonic() >= deadline:
                        return None
                    headers = {"Accept": "application/json", "Content-Type": "application/json"}
                    if key:
                        headers["Authorization"] = "Api-Key " + key
                    payload = json.dumps({
                        "url": url, "videoQuality": quality,
                        "youtubeVideoCodec": "h264", "downloadMode": "auto",
                        "localProcessing": "disabled",
                    }).encode()
                    request = urllib.request.Request(endpoint, data=payload, headers=headers)
                    with urllib.request.urlopen(request, timeout=15) as response:
                        data = json.loads(response.read(256 * 1024))
                    if data.get("status") not in ("tunnel", "redirect") or not data.get("url"):
                        break
                    path = self._media(data["url"], limit, deadline)
                    if path:
                        self.cooldowns.pop(endpoint, None)
                        print(f"[InstaDL] hosted provider {index + 1} downloaded {quality}")
                        return path
                    # None means oversized; try a lower quality without
                    # downloading an oversized file to completion.
            except Exception as error:
                # Do not print URLs, response bodies or credentials. Provider
                # exceptions can contain signed URLs or authentication data.
                print(f"[InstaDL] hosted provider {index + 1} failed: {type(error).__name__}")
                self.cooldowns[endpoint] = time.monotonic() + 300
        return None

    @staticmethod
    def _media(url, limit, deadline):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("invalid media URL")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as response:
                # Estimated-Content-Length is advisory and can overestimate.
                length = response.headers.get("Content-Length", "")
                if length.isdigit() and int(length) > limit:
                    return None
        except (urllib.error.URLError, TimeoutError):
            pass
        path = None
        keep = False
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                with tempfile.NamedTemporaryFile(prefix="midvox_hosted_", suffix=".mp4", delete=False) as output:
                    path = output.name
                    size = 0
                    first = True
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        if first:
                            # MP4/M4A starts with a file-type box; reject HTML,
                            # JSON error pages and arbitrary provider output.
                            if len(chunk) < 12 or chunk[4:8] != b"ftyp":
                                raise ValueError("invalid media")
                            first = False
                        size += len(chunk)
                        if size > limit:
                            return None
                        output.write(chunk)
                    if size == 0:
                        raise ValueError("empty media")
                    keep = True
                    return path
        finally:
            if path and not keep:
                os.unlink(path)
