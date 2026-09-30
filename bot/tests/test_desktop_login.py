"""Regression coverage for Discord's removed localStorage global."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import bump_sidecar as sidecar


class DesktopLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_desktop_liveness_uses_the_process_group(self):
        process = SimpleNamespace(pid=1234, returncode=0)

        with patch.object(sidecar.os, "killpg", create=True) as killpg:
            self.assertTrue(sidecar.desktop_process_group_alive(process))
            killpg.assert_called_once_with(1234, 0)

        with patch.object(
            sidecar.os,
            "killpg",
            side_effect=ProcessLookupError,
            create=True,
        ):
            self.assertFalse(sidecar.desktop_process_group_alive(process))

    def test_interaction_gateway_does_not_override_presence(self):
        payload = sidecar.gateway_identify_payload()

        self.assertEqual(payload["op"], 2)
        self.assertNotIn("presence", payload["d"])

    def test_desktop_target_excludes_web_login_and_untrusted_hosts(self):
        self.assertTrue(sidecar.is_desktop_app_url("https://discordapp.com/app"))
        self.assertTrue(sidecar.is_desktop_app_url("https://discord.com/app/"))
        for url in (
            "https://discord.com/login", "https://discord.com/channels/@me",
            "https://example.com/discord.com/app", "https://discord.com.evil/app",
            "file:///app", "https://discord.com/application",
        ):
            self.assertFalse(sidecar.is_desktop_app_url(url), url)

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

        target = {"type": "page", "url": "https://discordapp.com/app",
                  "webSocketDebuggerUrl": "ws://localhost/test"}
        session = MagicMock()
        session.get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value=[target]
        )
        call = AsyncMock(side_effect=[{}, {"entries": [["token", stored]]}, {}])
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
        self.assertNotIn("Page.navigate", methods)
        self.assertEqual(
            call.call_args_list[0].args[3]["storageId"]["securityOrigin"],
            "https://discordapp.com",
        )
        self.assertEqual("Page.reload" in methods, succeeds)


if __name__ == "__main__":
    unittest.main()
