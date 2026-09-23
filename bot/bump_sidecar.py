import asyncio
import json
import os

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
API = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"


async def loop():
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s", flush=True)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.post(
                    API, headers=headers, json={"content": "/bump"}
                ) as r:
                    body = await r.text()
                    print(f"[bump] {r.status} {body}", flush=True)
                    if r.status == 429:
                        try:
                            retry = float(json.loads(body).get("retry_after", 10))
                        except Exception:
                            retry = 10
                        await asyncio.sleep(retry)
                        continue
            except Exception as e:
                print(f"[bump] error: {e}", flush=True)
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    if not TOKEN or not CHANNEL_ID:
        raise SystemExit("USER_TOKEN and BUMP_CHANNEL_ID required")
    asyncio.run(loop())
