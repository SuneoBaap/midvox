"""End-to-end test of the user Gateway loop against a fake Discord server.

Covers: Identify -> READY -> single online announcement -> abnormal close ->
Resume (op 6) -> RESUMED with no republish, without touching Discord.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("USER_TOKEN", "test-user-token")

from aiohttp import web

import bump_sidecar

SPOTIFY_ACTIVITY = {
    "id": "spotify:1",
    "name": "Spotify",
    "type": 2,
    "details": "Test Song",
    "state": "Test Artist",
    "timestamps": {"start": 1790240000000, "end": 1790240180000},
    "assets": {"large_image": "spotify:image-1", "large_text": "Test Album"},
    "sync_id": "track123",
    "session_id": "local-pc",
    "flags": 48,
    "party": {"id": "spotify:user1"},
    "created_at": 1790240000000,
}

SESSIONS = [
    {
        "session_id": "sess-1",
        "status": "online",
        "client_info": {"client": "desktop", "os": "linux", "version": 0},
        "activities": [],
    },
    {
        "session_id": "local-pc",
        "status": "online",
        "client_info": {"client": "desktop", "os": "windows", "version": 0},
        "activities": [SPOTIFY_ACTIVITY],
    },
]


class FakeDiscordGateway:
    """Minimal fake server speaking just enough Gateway for the test."""

    def __init__(self):
        self.ws_url = ""
        self.got_identify = None
        self.presence_updates = []
        self.got_resume = None
        self._connections = 0

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._connections += 1
        try:
            if self._connections == 1:
                await self._first_session(ws)
            else:
                await self._resumed_session(ws)
        finally:
            await ws.close()
        return ws

    async def _send_hello(self, ws):
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 1000}})

    async def _serve_heartbeats(self, ws, stop):
        async for message in ws:
            if stop.is_set():
                return
            if message.type == web.WSMsgType.TEXT:
                payload = json.loads(message.data)
                if payload.get("op") == 1:
                    await ws.send_json({"op": 11})
                elif payload.get("op") == 3:
                    self.presence_updates.append(payload)
            else:
                return

    async def _first_session(self, ws):
        await self._send_hello(ws)
        identify = await asyncio.wait_for(ws.receive_json(), timeout=10)
        assert identify["op"] == 2, identify
        self.got_identify = identify
        await ws.send_json(
            {
                "op": 0,
                "s": 1,
                "t": "READY",
                "d": {
                    "session_id": "sess-1",
                    "resume_gateway_url": self.ws_url,
                    "sessions": SESSIONS,
                },
            }
        )
        stop = asyncio.Event()
        reader = asyncio.create_task(self._serve_heartbeats(ws, stop))
        try:
            await asyncio.wait_for(self._wait_for_presence(), timeout=10)
        finally:
            stop.set()
        # Re-send the identical session list: the client must suppress a
        # duplicate presence update.
        await ws.send_json({"op": 0, "s": 2, "t": "SESSIONS_REPLACE", "d": SESSIONS})
        await asyncio.sleep(1.5)
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await ws.close(code=1006)

    async def _wait_for_presence(self):
        while not self.presence_updates:
            await asyncio.sleep(0.05)

    async def _resumed_session(self, ws):
        await self._send_hello(ws)
        resume = await asyncio.wait_for(ws.receive_json(), timeout=10)
        assert resume["op"] == 6, resume
        self.got_resume = resume
        await ws.send_json({"op": 0, "s": 3, "t": "RESUMED", "d": {}})
        stop = asyncio.Event()
        try:
            await self._serve_heartbeats(ws, stop)
        finally:
            stop.set()


class UserGatewayFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = FakeDiscordGateway()
        app = web.Application()
        app.router.add_get("/gateway", self.server.handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.runner.addresses[0][1]
        self.server.ws_url = (
            f"ws://127.0.0.1:{port}/gateway?v=10&encoding=json"
        )
        bump_sidecar.GATEWAY = self.server.ws_url
        bump_sidecar.RESUME_GATEWAY_URL = self.server.ws_url
        bump_sidecar.RESUME_SESSION_ID = ""
        bump_sidecar.RESUME_SEQ = None
        bump_sidecar.SESSION_ID = ""
        bump_sidecar.SESSION_READY.clear()
        bump_sidecar.RECONNECT_DELAY = 1.0
        self._tmp = tempfile.TemporaryDirectory()
        self.ready_file = os.path.join(self._tmp.name, "ready")
        bump_sidecar.USER_PRESENCE_READY_FILE = self.ready_file

    async def asyncTearDown(self):
        await self.runner.cleanup()
        self._tmp.cleanup()

    async def test_identify_mirror_and_resume(self):
        task = asyncio.create_task(bump_sidecar.connect_presence())
        try:
            await asyncio.wait_for(self._wait_until_resumed(), timeout=30)
            # Snapshot before cancelling: shutdown clears readiness by design.
            snapshot_ready = bump_sidecar.SESSION_READY.is_set()
            snapshot_session = bump_sidecar.SESSION_ID
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        identify = self.server.got_identify
        self.assertIsNotNone(identify)
        self.assertEqual(
            identify["d"]["properties"]["browser"], "Discord Client"
        )
        self.assertEqual(identify["d"]["presence"]["status"], "unknown")

        # Exactly one presence update: a single online announcement after
        # READY. SESSIONS_REPLACE is ignored and nothing is republished on
        # RESUMED, so Discord's native per-session display is left alone.
        # Heartbeats are not presence updates.
        self.assertEqual(len(self.server.presence_updates), 1)
        presence = self.server.presence_updates[0]["d"]
        self.assertEqual(presence["status"], "online")
        self.assertEqual(presence["activities"], [])

        resume = self.server.got_resume
        self.assertIsNotNone(resume)
        self.assertEqual(resume["d"]["session_id"], "sess-1")
        self.assertTrue(snapshot_ready)
        self.assertEqual(snapshot_session, "sess-1")

    async def _wait_until_resumed(self):
        while self.server.got_resume is None or not (
            bump_sidecar.SESSION_READY.is_set()
            and bump_sidecar.SESSION_ID == "sess-1"
        ):
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
