"""Regression coverage for Discord's removed localStorage global."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import bump_sidecar as sidecar


class DesktopLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_online_presence_is_green_and_not_idle(self):
        ws = AsyncMock()
        activities = [{"name": "Spotify", "type": 2}]

        await sidecar.publish_online(ws, activities)

        ws.send_json.assert_awaited_once_with(
            {
                "op": 3,
                "d": {
                    "status": "online",
                    "since": 0,
                    "activities": activities,
                    "afk": False,
                },
            }
        )

    async def test_desktop_activity_types_then_erases_without_sending(self):
        from unittest.mock import MagicMock

        target = {
            "type": "page",
            "url": "https://discord.com/channels/@me",
            "webSocketDebuggerUrl": "ws://localhost/test",
        }
        channel_response = MagicMock(status=200)
        channel_response.json = AsyncMock(return_value={"guild_id": "123"})
        target_response = MagicMock(status=200)
        target_response.json = AsyncMock(return_value=[target])
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(
                __aenter__=AsyncMock(return_value=channel_response),
                __aexit__=AsyncMock(return_value=False),
            ),
            MagicMock(
                __aenter__=AsyncMock(return_value=target_response),
                __aexit__=AsyncMock(return_value=False),
            ),
        ]
        session.ws_connect.return_value = MagicMock(
            __aenter__=AsyncMock(return_value=AsyncMock()),
            __aexit__=AsyncMock(return_value=False),
        )
        call = AsyncMock(
            side_effect=[{}, {"result": {"value": True}}, {}, {}, {}]
        )

        with patch.object(sidecar, "TOKEN", "test-token"), \
             patch.object(sidecar, "CHANNEL_ID", "456"), \
             patch.object(sidecar, "cdp_call", call), \
             patch.object(sidecar.asyncio, "sleep", AsyncMock()):
            await sidecar.wake_desktop_in_bump_channel(session, 9222)

        methods = [entry.args[2] for entry in call.call_args_list]
        self.assertEqual(
            methods,
            [
                "Page.navigate",
                "Runtime.evaluate",
                "Input.insertText",
                "Input.dispatchKeyEvent",
                "Input.dispatchKeyEvent",
            ],
        )
        self.assertNotIn("Enter", str(call.call_args_list))

    async def test_javascript_exception_is_not_success(self):
        import json
        from types import SimpleNamespace

        ws = AsyncMock()
        ws.receive.return_value = SimpleNamespace(
            type=sidecar.aiohttp.WSMsgType.TEXT,
            data=json.dumps({"id": 1, "result": {
                "exceptionDetails": {"text": "localStorage is not defined"}
            }}),
        )
        with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
            await sidecar.cdp_call(ws, 1, "Runtime.evaluate")

    async def test_handoff_verifies_storage_then_reloads(self):
        await self.run_handoff(stored='"test-only-token"', succeeds=True)

    async def test_failed_storage_never_reloads(self):
        await self.run_handoff(stored='"different-token"', succeeds=False)

    async def run_handoff(self, stored, succeeds):
        from unittest.mock import MagicMock

        target = {"type": "page", "url": "https://discord.com/login",
                  "webSocketDebuggerUrl": "ws://localhost/test"}
        session = MagicMock()
        session.get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value=[target]
        )
        call = AsyncMock(side_effect=[{}, {}, {"entries": [["token", stored]]}, {}])
        with patch.object(sidecar, "TOKEN", "test-only-token"), \
             patch.object(sidecar, "cdp_call", call), \
             patch.object(sidecar.asyncio, "sleep", AsyncMock()):
            if succeeds:
                await sidecar.authenticate_desktop(session, target, 9222)
            else:
                with self.assertRaisesRegex(RuntimeError, "storage verification failed"):
                    await sidecar.authenticate_desktop(session, target, 9222)
        methods = [c.args[2] for c in call.call_args_list]
        self.assertIn("DOMStorage.setDOMStorageItem", methods)
        self.assertNotIn("Runtime.evaluate", methods)
        self.assertEqual("Page.reload" in methods, succeeds)


if __name__ == "__main__":
    unittest.main()
