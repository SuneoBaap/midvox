"""Native reconnect recovery must distinguish failure from quiet playback."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from desktop_health import DesktopHealth


class DesktopHealthTests(unittest.TestCase):
    def test_spotify_stuck_connecting_has_bounded_recovery(self):
        health = DesktopHealth()
        health.observe("[Spotify] WS Connecting", now=10)
        health.observe("[Spotify] WS Connecting", now=100)
        self.assertFalse(health.spotify_reconnect_stalled(now=129))
        self.assertTrue(health.spotify_reconnect_stalled(now=130))

    def test_spotify_reconnect_clears_failure_independently_of_gateway(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [READY]", now=0)
        self.assertEqual(health.observe("[Spotify] WS Connected", now=1), "spotify_connected")
        self.assertEqual(health.observe("[Spotify] WS Disconnected", now=5), "spotify_disconnected")
        health.observe("[GatewaySocket] [READY_SUPPLEMENTAL]", now=50)
        self.assertTrue(health.spotify_reconnect_stalled(now=125))
        self.assertFalse(health.reconnect_stalled(now=125))
        health.observe("[Spotify] WS Connected", now=126)
        self.assertFalse(health.spotify_reconnect_stalled(now=1000))

    def test_quiet_playback_and_no_linked_account_do_not_trigger_recovery(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [READY]", now=0)
        self.assertFalse(health.spotify_reconnect_stalled(now=10000))
        health.observe("[Spotify] WS Connected", now=1)
        health.observe("[Spotify] Devices updated: []", now=2)
        health.observe("[Spotify] Player paused", now=3)
        self.assertFalse(health.spotify_reconnect_stalled(now=10000))

    def test_stuck_reconnect_and_retries_do_not_reset_deadline(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [READY]", now=0)
        self.assertEqual(health.observe("[GatewaySocket] [CLOSE] 1006", now=10), "disconnected")
        health.observe("[GatewaySocket] Setting connection state to CONNECTING", now=100)
        self.assertFalse(health.reconnect_stalled(now=129))
        self.assertTrue(health.reconnect_stalled(now=130))

    def test_successful_native_reconnect_cancels_recovery(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [READY]", now=0)
        health.observe("[GatewaySocket] Setting connection state to WILL_RECONNECT", now=5)
        self.assertEqual(health.observe("[GatewaySocket] [RESUMED]", now=25), "connected")
        self.assertFalse(health.reconnect_stalled(now=1000))

    def test_connected_socket_is_not_yet_authenticated(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [CONNECTED]", now=0)
        self.assertFalse(health.connected)
        health.observe("[GatewaySocket] Setting connection state to SESSION_ESTABLISHED", now=1)
        self.assertTrue(health.connected)

    def test_paused_spotify_and_idle_logs_never_restart_desktop(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] [READY]", now=0)
        health.observe("[Spotify] Devices updated: []", now=1)
        health.observe("[Spotify] Player paused", now=2)
        health.observe("normal idle session", now=3)
        self.assertFalse(health.reconnect_stalled(now=10000))

    def test_initial_connecting_uses_startup_timeout_instead(self):
        health = DesktopHealth()
        health.observe("[GatewaySocket] Setting connection state to CONNECTING", now=0)
        self.assertFalse(health.reconnect_stalled(now=1000))
