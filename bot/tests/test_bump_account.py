import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch
import bump_sidecar as worker


class BumpAccountTests(unittest.IsolatedAsyncioTestCase):
    def test_environment_overrides_saved_login(self):
        with patch.object(worker.os.path, "isfile", return_value=True), patch(
            "builtins.open", mock_open(read_data='{"token":"saved"}')
        ) as saved, patch.dict(worker.os.environ, {"USER_TOKEN": " configured "}):
            self.assertEqual(worker.configured_account_token(), "configured")
            saved.assert_not_called()

    def test_damaged_saved_login_is_ignored(self):
        with patch.object(worker.os.path, "isfile", return_value=True), patch(
            "builtins.open", mock_open(read_data="{}")
        ), patch.dict(worker.os.environ, {"USER_TOKEN": "configured"}):
            self.assertEqual(worker.configured_account_token(), "configured")

    def test_missing_environment_never_falls_back_to_saved_account(self):
        with patch("builtins.open", mock_open(read_data='{"token":"saved"}')) as saved, \
             patch.dict(worker.os.environ, {"USER_TOKEN": "   "}):
            self.assertEqual(worker.configured_account_token(), "")
            saved.assert_not_called()

    async def test_403_is_transient_and_401_requires_new_login(self):
        for status, error in ((403, RuntimeError), (401, worker.InvalidCredential)):
            response = MagicMock(status=status)
            request = MagicMock()
            request.__aenter__ = AsyncMock(return_value=response)
            request.__aexit__ = AsyncMock(return_value=False)
            session = MagicMock()
            session.get.return_value = request
            with self.assertRaises(error) as caught:
                await worker.validate_user_token(session)
            if status == 403:
                self.assertNotIsInstance(caught.exception, worker.InvalidCredential)
            self.assertIn("Mozilla", session.get.call_args.kwargs["headers"]["User-Agent"])

    async def test_missing_heartbeat_ack_closes_stale_socket(self):
        socket = MagicMock(closed=False)
        socket.close = AsyncMock()
        socket.send_json = AsyncMock()
        with patch.object(worker.asyncio, "sleep", AsyncMock()):
            await worker.heartbeat(socket, 30, [None], [False])
        socket.close.assert_awaited_once()
        socket.send_json.assert_not_awaited()
