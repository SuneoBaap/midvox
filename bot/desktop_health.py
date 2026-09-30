"""Track confirmed native Discord connection loss without publishing presence."""

import time


class DesktopHealth:
    RECONNECT_GRACE_SECONDS = 120

    def __init__(self):
        self.connected = False
        self.ever_connected = False
        self.disconnected_since = None
        self.spotify_connected = False
        self.spotify_disconnected_since = None

    def observe(self, line, now=None):
        """Return a connection transition from the official client's logs."""
        now = time.monotonic() if now is None else now
        if "[Spotify]" in line:
            if "WS Connected" in line:
                transitioned = not self.spotify_connected
                self.spotify_connected = True
                self.spotify_disconnected_since = None
                return "spotify_connected" if transitioned else None
            if any(marker in line for marker in (
                "WS Connecting", "WS Disconnected", "WS Closed", "WS Error",
            )):
                transitioned = self.spotify_connected
                self.spotify_connected = False
                if self.spotify_disconnected_since is None:
                    self.spotify_disconnected_since = now
                return "spotify_disconnected" if transitioned else None
        if "[GatewaySocket]" not in line:
            return None
        established = (
            "[READY]" in line or "[RESUMED]" in line
            or "Setting connection state to SESSION_ESTABLISHED" in line
        )
        if established:
            transitioned = not self.connected
            self.connected = self.ever_connected = True
            self.disconnected_since = None
            return "connected" if transitioned else None
        lost = any(marker in line for marker in (
            "[CLOSE]", "[CLOSED]", "[DISCONNECT]",
            "Setting connection state to DISCONNECTED",
            "Setting connection state to WILL_RECONNECT",
            "Setting connection state to CONNECTING",
        ))
        if lost and self.ever_connected:
            transitioned = self.connected
            self.connected = False
            # Repeated failed attempts must not extend the grace period.
            if self.disconnected_since is None:
                self.disconnected_since = now
            return "disconnected" if transitioned else None
        return None

    def reconnect_stalled(self, now=None):
        now = time.monotonic() if now is None else now
        return (
            self.disconnected_since is not None
            and now - self.disconnected_since >= self.RECONNECT_GRACE_SECONDS
        )

    def spotify_reconnect_stalled(self, now=None):
        """Only recover an explicit socket failure or unfinished connection."""
        now = time.monotonic() if now is None else now
        return (
            self.spotify_disconnected_since is not None
            and now - self.spotify_disconnected_since >= self.RECONNECT_GRACE_SECONDS
        )
