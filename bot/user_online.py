"""Keep a user token online. Nothing else.

One gateway connection: identify, heartbeat, resume across drops. No bump,
no presence edits, no mirroring. Set ONLINE_CLIENT=android for the mobile
status icon, anything else (default) shows desktop.
"""

import asyncio
import json
import os
import random
import time

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "").strip()
CLIENT = os.getenv("ONLINE_CLIENT", "desktop").strip().lower()
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"

PROPERTIES = {
    "android": {
        "os": "Android",
        "browser": "Discord Android",
        "device": "OnePlus 7 Pro",
        "system_locale": "en-US",
    },
    "desktop": {
        "os": "Linux",
        "browser": "Discord Client",
        "device": "",
        "system_locale": "en-US",
    },
}.get(CLIENT, {
    "os": "Linux",
    "browser": "Discord Client",
    "device": "",
    "system_locale": "en-US",
})

BACKOFF = 1.0
URL = GATEWAY
SESSION = ""
SEQ = None


async def heartbeat(ws, interval, seq, acked):
    await asyncio.sleep(random.uniform(0, min(2.0, interval)))
    while not ws.closed:
        await ws.send_json({"op": 1, "d": seq[0]})
        sent = time.monotonic()
        await asyncio.sleep(interval)
        if acked[0] < sent:
            raise RuntimeError("gateway did not acknowledge heartbeat")


async def main():
    global BACKOFF, URL, SESSION, SEQ
    if not TOKEN:
        raise SystemExit("USER_TOKEN required")

    while True:
        resume = bool(SESSION)
        try:
            async with aiohttp.ClientSession() as http:
                async with http.ws_connect(URL, heartbeat=None) as ws:
                    hello = await asyncio.wait_for(ws.receive_json(), timeout=20)
                    if hello.get("op") != 10:
                        raise RuntimeError("no HELLO from gateway")
                    interval = hello["d"]["heartbeat_interval"] / 1000
                    seq, acked = [SEQ], [time.monotonic()]
                    beats = asyncio.create_task(heartbeat(ws, interval, seq, acked))
                    try:
                        if resume:
                            await ws.send_json(
                                {"op": 6, "d": {"token": TOKEN, "session_id": SESSION, "seq": SEQ}}
                            )
                            print("[online] resuming session", flush=True)
                        else:
                            await ws.send_json(
                                {
                                    "op": 2,
                                    "d": {
                                        "token": TOKEN,
                                        "properties": PROPERTIES,
                                        "presence": {
                                            "status": "online",
                                            "since": 0,
                                            "activities": [],
                                            "afk": False,
                                        },
                                    },
                                }
                            )
                            print("[online] identifying as " + CLIENT, flush=True)
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                break
                            p = json.loads(msg.data)
                            if p.get("s") is not None:
                                seq[0] = p["s"]
                                SEQ = p["s"]
                            op, event = p.get("op"), p.get("t")
                            if op == 11:
                                acked[0] = time.monotonic()
                            elif op == 0 and event == "READY":
                                d = p.get("d", {})
                                SESSION = str(d.get("session_id") or "")
                                URL = str(d.get("resume_gateway_url") or GATEWAY)
                                BACKOFF = 1.0
                                print(
                                    f"[online] ONLINE ({CLIENT}) session {SESSION[:8]}…",
                                    flush=True,
                                )
                            elif op == 0 and event == "RESUMED":
                                BACKOFF = 1.0
                                print("[online] resumed, still online", flush=True)
                            elif op == 1:
                                await ws.send_json({"op": 1, "d": seq[0]})
                            elif op == 7:
                                break  # reconnect -> resume (SESSION kept)
                            elif op == 9:
                                if not p.get("d"):
                                    SESSION, SEQ, URL = "", None, GATEWAY
                                break
                        if ws.close_code == 4004:
                            print(
                                "[online] FATAL: Discord rejected USER_TOKEN "
                                "(4004). Wrong token, password changed, or "
                                "account locked.",
                                flush=True,
                            )
                            raise SystemExit(1)
                    finally:
                        beats.cancel()
                        await asyncio.gather(beats, return_exceptions=True)
        except SystemExit:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[online] dropped: {error}", flush=True)
        print(f"[online] retry in {BACKOFF:g}s", flush=True)
        await asyncio.sleep(BACKOFF)
        BACKOFF = min(BACKOFF * 2, 30.0)


if __name__ == "__main__":
    asyncio.run(main())
