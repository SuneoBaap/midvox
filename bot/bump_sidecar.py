import asyncio
import json
import os
import random
import string

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "7200"))  # Disboard is 2h
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"


def nonce() -> str:
    return "".join(random.choices(string.digits, k=18))


async def send_bump(session: aiohttp.ClientSession, headers: dict) -> None:
    # 1. Resolve guild_id from the channel
    async with session.get(f"{API_BASE}/channels/{CHANNEL_ID}", headers=headers) as r:
        if r.status != 200:
            body = await r.text()
            print(f"[bump] channel lookup failed {r.status} {body}", flush=True)
            return
        data = await r.json()
        guild_id = data.get("guild_id")
        if not guild_id:
            print("[bump] channel has no guild_id (DM?)", flush=True)
            return

    # 2. Fire the actual /bump slash command
    payload = {
        "type": 2,  # APPLICATION_COMMAND
        "application_id": DISBOARD_APP_ID,
        "guild_id": str(guild_id),
        "channel_id": str(CHANNEL_ID),
        "session_id": nonce(),
        "data": {
            "version": "1051151065191559209",  # current /bump version
            "id": "947088344167366698",       # /bump command id
            "name": "bump",
            "type": 1,
            "options": [],
            "application_command": {
                "id": "947088344167366698",
                "application_id": DISBOARD_APP_ID,
                "version": "1051151065191559209",
                "default_member_permissions": None,
                "type": 1,
                "name": "bump",
                "description": "Bump this server",
                "dm_permission": True,
                "contexts": None,
                "integration_types": [0],
            },
            "attachments": [],
        },
        "nonce": nonce(),
    }

    async with session.post(
        f"{API_BASE}/interactions",
        headers=headers,
        json=payload,
    ) as r:
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
        "Authorization": TOKEN,          # user token, NOT bot token
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiRGlzY29yZCBDbGllbnQiLCJkZXZpY2UiOiJkZXNrdG9wIn0=",
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
