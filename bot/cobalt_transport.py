"""Recover one local Cobalt request when its supervised process restarts."""

from http.client import RemoteDisconnected
import time
import urllib.error
import urllib.request


def open_cobalt_request(request, base_url, *, timeout=40, recovery_seconds=10):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        # An extraction/login error is a response, not a process crash.
        raise
    except (RemoteDisconnected, ConnectionError, urllib.error.URLError, TimeoutError):
        deadline = time.monotonic() + recovery_seconds
        while time.monotonic() < deadline:
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                with urllib.request.urlopen(base_url.rstrip("/") + "/", timeout=min(1, remaining)):
                    pass
            except (OSError, urllib.error.URLError):
                continue
            print("[InstaDL] Cobalt recovered; retrying the interrupted request once")
            return urllib.request.urlopen(request, timeout=timeout)
        raise
