import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from gateway_resume import next_backoff, should_resume


class GatewayResumeTests(unittest.TestCase):
    def test_resumes_transport_drop_with_saved_session(self):
        self.assertTrue(should_resume(None, None, True))
        self.assertTrue(should_resume(None, 1006, True))
        self.assertTrue(should_resume(True, None, True))

    def test_reconnect_request_uses_saved_session(self):
        # op 7 leaves invalid_resumable unset; a saved session may resume.
        self.assertTrue(should_resume(None, None, True))

    def test_fresh_session_on_explicit_close(self):
        self.assertFalse(should_resume(None, 1000, True))
        self.assertFalse(should_resume(None, 1001, True))

    def test_fresh_session_on_auth_failure(self):
        # 4004 = Discord rejected the token; resuming can never succeed.
        self.assertFalse(should_resume(None, 4004, True))
        self.assertFalse(should_resume(None, 4004, False))

    def test_fresh_session_on_non_resumable_invalid_session(self):
        self.assertFalse(should_resume(False, None, True))

    def test_fresh_session_without_saved_session(self):
        self.assertFalse(should_resume(None, None, False))
        self.assertFalse(should_resume(True, None, False))

    def test_backoff_grows_and_caps(self):
        self.assertEqual(next_backoff(1.0), 2.0)
        self.assertEqual(next_backoff(16.0), 30.0)
        self.assertEqual(next_backoff(30.0), 30.0)


if __name__ == "__main__":
    unittest.main()
