"""Regression coverage for Discord's removed localStorage global."""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import bump_sidecar as sidecar


class DesktopLoginTests(unittest.IsolatedAsyncioTestCase):
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
