from http.client import RemoteDisconnected
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cobalt_transport import open_cobalt_request


class CobaltTransportTests(unittest.TestCase):
    def setUp(self):
        self.request = urllib.request.Request("http://127.0.0.1:9000", data=b'{"url":"short"}')

    def test_restart_retries_same_request_after_health_recovers(self):
        response = MagicMock()
        with patch("cobalt_transport.urllib.request.urlopen", side_effect=[RemoteDisconnected(), MagicMock(), response]) as opened, \
             patch("cobalt_transport.time.sleep"):
            self.assertIs(open_cobalt_request(self.request, "http://127.0.0.1:9000"), response)
        self.assertIs(opened.call_args_list[0].args[0], self.request)
        self.assertEqual(opened.call_args_list[1].args[0], "http://127.0.0.1:9000/")
        self.assertIs(opened.call_args_list[2].args[0], self.request)

    def test_http_extraction_errors_are_not_retried(self):
        error = urllib.error.HTTPError(self.request.full_url, 400, "login", {}, None)
        with patch("cobalt_transport.urllib.request.urlopen", side_effect=error) as opened:
            with self.assertRaises(urllib.error.HTTPError):
                open_cobalt_request(self.request, "http://127.0.0.1:9000")
        self.assertEqual(opened.call_count, 1)

    def test_unavailable_service_has_bounded_recovery(self):
        with patch("cobalt_transport.urllib.request.urlopen", side_effect=RemoteDisconnected()) as opened, \
             patch("cobalt_transport.time.monotonic", side_effect=[0, 11]):
            with self.assertRaises(RemoteDisconnected):
                open_cobalt_request(self.request, "http://127.0.0.1:9000")
        self.assertEqual(opened.call_count, 1)

    def test_second_disconnect_is_not_retried_again(self):
        with patch("cobalt_transport.urllib.request.urlopen", side_effect=[RemoteDisconnected(), MagicMock(), RemoteDisconnected()]) as opened, \
             patch("cobalt_transport.time.sleep"):
            with self.assertRaises(RemoteDisconnected):
                open_cobalt_request(self.request, "http://127.0.0.1:9000")
        self.assertEqual(opened.call_count, 3)
