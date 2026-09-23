import asyncio
import json
import os
import random
import string

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "7200"))
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"


def nonce() -> str:
    return "".join(random.choices(string.digits, k=18))


async def fetch_bump_command(session: aiohttp.ClientSession, headers: dict, guild_id: str):
    # Prefer guild-scoped commands (most accurate for installed bots)
    urls = [
        f"{API_BASE}/applications/{DISBOARD_APP_ID}/guilds/{guild_id}/commands",
        f"{API_BASE}/applications/{DISBOARD_APP_ID}/commands",
    ]
    for url in urls:
        async with session.get(url, headers=headers) as r:
            body = await r.text()
            if r.status != 200:
                print(f"[bump] command list {r.status} from {url}: {body[:200]}", flush=True)
                continue
            try:
                cmds = json.loads(body)
            except Exception:
                continue
            for c in cmds:
                if c.get("name") == "bump" and c.get("type", 1) == 1:
                    print(f"[bump] found live command id={c['id']} version={c.get('version')}", flush=True)
                    return c
    return None


async def send_bump(session: aiohttp.ClientSession, headers: dict) -> None:
    # 1. Resolve guild_id
    async with session.get(f"{API_BASE}/channels/{CHANNEL_ID}", headers=headers) as r:
        if r.status != 200:
            body = await r.text()
            print(f"[bump] channel lookup failed {r.status} {body}", flush=True)
            return
        data = await r.json()
        guild_id = data.get("guild_id")
        if not guild_id:
            print("[bump] channel has no guild_id", flush=True)
            return

    # 2. Get current /bump command definition
    cmd = await fetch_bump_command(session, headers, str(guild_id))
    if not cmd:
        print("[bump] could not resolve /bump command — Disboard may be down or not in guild", flush=True)
        return

    # 3. Fire interaction with live id + version
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
            print(f"[bump] rate limited, sleeping {retry}s", flush=True)
            await asyncio.sleep(retry)


async def loop():
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyMzgxNiwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=",
    }
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s (Disboard {DISBOARD_APP_ID})", flush=True)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await send_bump(session, headers)
            except Exception as e:
                print(f"[bump] error: {e}", flush=True)
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    if not TOKEN or not CHANNEL_ID:
        raise SystemExit("USER_TOKEN and BUMP_CHANNEL_ID required")
    asyncio.run(loop())
