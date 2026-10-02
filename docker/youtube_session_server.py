"""Low-memory Cobalt session adapter for the local Rust BotGuard provider."""

import html
import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.getenv("YT_SESSION_HOST", "127.0.0.1")
PORT = int(os.getenv("YT_SESSION_PORT", "8081"))
PROVIDER = os.getenv("YT_POT_PROVIDER", "http://127.0.0.1:4416/get_pot")
PROXY = os.getenv("COBALT_PROXY_URL", "").strip()
TOKEN_TTL = max(300, int(os.getenv("YT_SESSION_TTL", "18000")))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

_cached = None
_lock = threading.Lock()


def _youtube_opener():
    handlers = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    return urllib.request.build_opener(*handlers)


def _visitor_data():
    request = urllib.request.Request(
        "https://www.youtube.com/",
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    page = _youtube_opener().open(request, timeout=25).read().decode("utf-8", "replace")
    for pattern in (r'"VISITOR_DATA":"([^"]+)"', r'"visitorData":"([^"]+)"'):
        match = re.search(pattern, page)
        if match:
            return html.unescape(json.loads(f'"{match.group(1)}"'))
    raise RuntimeError("YouTube response did not contain visitor data")


def _generate():
    visitor = _visitor_data()
    body = {"content_binding": visitor, "bypass_cache": False}
    if PROXY:
        body["proxy"] = PROXY
    request = urllib.request.Request(
        PROVIDER,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = json.load(urllib.request.urlopen(request, timeout=60))
    token = result.get("poToken") or result.get("po_token")
    if not token:
        raise RuntimeError("BotGuard provider returned no PoToken")
    return {
        "poToken": token,
        "contentBinding": visitor,
        "potoken": token,
        "visitor_data": visitor,
        "updated": int(time.time()),
    }


def session(force=False):
    global _cached
    with _lock:
        if not force and _cached and time.time() - _cached["updated"] < TOKEN_TTL:
            return _cached
        _cached = _generate()
        print("[yt-session] refreshed YouTube session token", flush=True)
        return _cached


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200 if _cached else 503, {"ready": bool(_cached)})
        elif self.path == "/token":
            self._serve(False)
        elif self.path == "/update":
            self._serve(True)
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/get_pot":
            self._serve(False)
        elif self.path == "/update":
            self._serve(True)
        else:
            self._json(404, {"error": "not_found"})

    def _serve(self, force):
        try:
            self._json(200, session(force))
        except Exception as error:
            print(f"[yt-session] generation failed: {error}", flush=True)
            self._json(503, {"error": "session_generation_failed"})


def _warmup():
    try:
        session()
    except Exception as error:
        print(f"[yt-session] initial generation failed: {error}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[yt-session] listening on http://{HOST}:{PORT}", flush=True)
    threading.Thread(target=_warmup, daemon=True).start()
    server.serve_forever()
