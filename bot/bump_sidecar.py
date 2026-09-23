import asyncio
import json
import os
import random
import string
import time

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))  # 10 min
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"


def nonce() -> str:
    return "".join(random.choices(string.digits, k=18))


async def fetch_bump_command(session: aiohttp.ClientSession, headers: dict, guild_id: str):
    urls = [
        f"{API_BASE}/channels/{CHANNEL_ID}/application-command-index",
        f"{API_BASE}/guilds/{guild_id}/application-command-index",
    ]
    for url in urls:
        async with session.get(url, headers=headers) as r:
            body = await r.text()
            if r.status != 200:
                print(f"[bump] index {r.status} from {url.split('/')[-2]}", flush=True)
                continue
            try:
                data = json.loads(body)
            except Exception:
                continue
            cmds = data.get("application_commands") or data.get("commands") or []
            for c in cmds:
                if (
                    str(c.get("application_id")) == DISBOARD_APP_ID
                    and c.get("name") == "bump"
                    and int(c.get("type", 1)) == 1
                ):
                    print(f"[bump] found live id={c['id']} version={c.get('version')}", flush=True)
                    return c
    return None


async def send_bump(session: aiohttp.ClientSession, headers: dict) -> None:
    async with session.get(f"{API_BASE}/channels/{CHANNEL_ID}", headers=headers) as r:
        if r.status != 200:
            print(f"[bump] channel lookup {r.status} {await r.text()}", flush=True)
            return
        guild_id = (await r.json()).get("guild_id")
        if not guild_id:
            print("[bump] no guild_id", flush=True)
            return

    cmd = await fetch_bump_command(session, headers, str(guild_id))
    if not cmd:
        print("[bump] /bump not found in index", flush=True)
        return

    payload = {
        "type": 2,
        "application_id": DISBOARD_APP_ID,
        "guild_id": str(guild_id),
        "channel_id": str(CHANNEL_ID),
        "session_id": nonce(),
        "data": {
            "version": str(cmd.get("version") or cmd["id"]),
            "id": str(cmd["id"]),
            "name": "bump",
            "type": 1,
            "options": [],
            "application_command": {
                "id": str(cmd["id"]),
                "application_id": DISBOARD_APP_ID,
                "version": str(cmd.get("version") or cmd["id"]),
                "type": 1,
                "name": "bump",
                "description": cmd.get("description") or "Bump this server",
                "dm_permission": cmd.get("dm_permission", True),
                "integration_types": cmd.get("integration_types") or [0],
            },
            "attachments": [],
        },
        "nonce": nonce(),
    }

    async with session.post(f"{API_BASE}/interactions", headers=headers, json=payload) as r:
        body = await r.text()
        print(f"[bump] interaction {r.status} {body}", flush=True)
        if r.status == 429:
            try:
                retry = float(json.loads(body).get("retry_after", 10))
            except Exception:
                retry = 10
            await asyncio.sleep(retry)


async def keep_online(session: aiohttp.ClientSession, headers: dict):
    """Maintain online presence via gateway."""
    while True:
        try:
            async with session.ws_connect(GATEWAY) as ws:
                # HELLO
                msg = await ws.receive_json()
                heartbeat_interval = msg["d"]["heartbeat_interval"] / 1000.0
                print(f"[presence] connected, heartbeat every {heartbeat_interval:.1f}s", flush=True)

                # IDENTIFY
                await ws.send_json({
                    "op": 2,
                    "d": {
                        "token": TOKEN,
                        "properties": {
                            "os": "Windows",
                            "browser": "Discord Client",
                            "device": "desktop",
                        },
                        "presence": {
                            "status": "online",
                            "since": 0,
                            "activities": [],
                            "afk": False,
                        },
                        "compress": False,
                        "intents": 0,
                    },
                })

                last_heartbeat = time.time()
                while True:
                    # Heartbeat on schedule
                    now = time.time()
                    if now - last_heartbeat >= heartbeat_interval:
                        await ws.send_json({"op": 1, "d": None})
                        last_heartbeat = now

                    try:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue

                    op = msg.get("op")
                    if op == 11:  # HEARTBEAT_ACK
                        pass
                    elif op == 7:  # RECONNECT
                        print("[presence] reconnect requested", flush=True)
                        break
                    elif op == 9:  # INVALID SESSION
                        print("[presence] invalid session, restarting", flush=True)
                        await asyncio.sleep(2)
                        break
                    elif op == 0 and msg.get("t") == "READY":
                        print(f"[presence] READY as {msg['d']['user']['username']}", flush=True)
        except Exception as e:
            print(f"[presence] error: {e} — retry in 10s", flush=True)
            await asyncio.sleep(10)


async def bump_loop(session: aiohttp.ClientSession, headers: dict):
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s", flush=True)
    while True:
        try:
            await send_bump(session, headers)
        except Exception as e:
            print(f"[bump] error: {e}", flush=True)
        await asyncio.sleep(INTERVAL)


async def main():
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyMzgxNiwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=",
    }
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            keep_online(session, headers),
            bump_loop(session, headers),
        )


if __name__ == "__main__":
    if not TOKEN or not CHANNEL_ID:
        raise SystemExit("USER_TOKEN and BUMP_CHANNEL_ID required")
    asyncio.run(main())
