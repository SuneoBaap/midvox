import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, mock_open, patch
import bump_sidecar as worker


class BumpAccountTests(unittest.IsolatedAsyncioTestCase):
    def test_saved_login_overrides_environment(self):
        with patch.object(worker.os.path, "isfile", return_value=True), patch(
            "builtins.open", mock_open(read_data=json.dumps({"token": "saved"}))
        ), patch.dict(worker.os.environ, {"USER_TOKEN": "old"}):
            self.assertEqual(worker.configured_account_token(), "saved")

    def test_damaged_saved_login_does_not_switch_accounts(self):
        with patch.object(worker.os.path, "isfile", return_value=True), patch(
            "builtins.open", mock_open(read_data="{}")
        ), patch.dict(worker.os.environ, {"USER_TOKEN": "old"}):
            with self.assertRaises(ValueError):
                worker.configured_account_token()

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
