"""Tests for the official-desktop login handoff.

Uses a fake Chrome DevTools endpoint: verifies the token is written on the
app's own target and that a full reload (not an SPA navigation) completes the
login. Also verifies only a real numeric user login marks the desktop ready.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import aiohttp
from aiohttp import web

import bump_sidecar


class FakeCDP:
    """Minimal DevTools endpoint answering evaluate/reload commands."""

    def __init__(self, evaluate_result):
        self.evaluate_result = evaluate_result
        self.reload_attempted = False

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            if message.type != web.WSMsgType.TEXT:
                break
            command = json.loads(message.data)
            if command.get("method") == "Runtime.evaluate":
                await ws.send_json(
                    {
                        "id": command["id"],
                        "result": {"result": {"value": self.evaluate_result}},
                    }
                )
            elif command.get("method") == "Page.reload":
                self.reload_attempted = True
                await ws.send_json({"id": command["id"], "result": {}})
                await ws.close()
        return ws


class DesktopAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_ready_file = bump_sidecar.USER_DESKTOP_READY_FILE
        bump_sidecar.USER_DESKTOP_READY_FILE = os.path.join(
            self._tmp.name, "desktop-ready"
        )

    async def asyncTearDown(self):
        bump_sidecar.USER_DESKTOP_READY_FILE = self._orig_ready_file
        self._tmp.cleanup()

    async def _run_handoff(self, evaluate_result):
        fake = FakeCDP(evaluate_result)
        app = web.Application()
        app.router.add_get("/cdp", fake.handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            port = runner.addresses[0][1]
            target = {"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/cdp"}
            async with aiohttp.ClientSession() as session:
                result = await asyncio.wait_for(
                    bump_sidecar.authenticate_desktop(session, target),
                    timeout=15,
                )
        finally:
            await runner.cleanup()
        return result, fake.reload_attempted

    async def test_stored_token_triggers_full_reload(self):
        reused, reloaded = await self._run_handoff("stored")
        self.assertFalse(reused)
        self.assertTrue(reloaded)

    async def test_existing_login_skips_reload(self):
        reused, reloaded = await self._run_handoff("ready")
        self.assertTrue(reused)
        self.assertFalse(reloaded)

    async def test_logged_out_gateway_ready_is_not_ready(self):
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"[discord-desktop] [DatabaseManager] active user changed "
            b"(now: undefined, was: null, was: undefined)\n"
        )
        reader.feed_data(b"[discord-desktop] [GatewaySocket] [READY] took 5ms\n")
        reader.feed_eof()
        await bump_sidecar.relay_desktop_output(reader)
        self.assertFalse(
            os.path.exists(bump_sidecar.USER_DESKTOP_READY_FILE)
        )

    async def test_numeric_login_marks_desktop_ready(self):
        reader = asyncio.StreamReader()
        reader.feed_data(
            b"[discord-desktop] [DatabaseManager] active user changed "
            b"(now: 1455646785635614792, was: null, was: undefined)\n"
        )
        reader.feed_eof()
        await bump_sidecar.relay_desktop_output(reader)
        with open(bump_sidecar.USER_DESKTOP_READY_FILE, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "1455646785635614792")


if __name__ == "__main__":
    unittest.main()
