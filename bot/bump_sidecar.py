import asyncio
import os
import time
import aiohttp

TOKEN = os.environ["USER_TOKEN"]
CHANNEL_ID = os.environ["BUMP_CHANNEL_ID"]
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
API = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"

async def loop():
    headers = {
        "Authorization": TOKEN,  # user token: no "Bot " prefix
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.post(API, headers=headers, json={"content": "/bump"}) as r:
                    print(f"[bump] {r.status} {await r.text()}", flush=True)
                    if r.status == 429:
                        retry = float((await r.json()).get("retry_after", 10))
                        await asyncio.sleep(retry)
                        continue
            except Exception as e:
                print(f"[bump] error: {e}", flush=True)
            await asyncio.sleep(INTERVAL)

if __name__ == "__main__":
    if not TOKEN or not CHANNEL_ID:
        raise SystemExit("USER_TOKEN and BUMP_CHANNEL_ID required")
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s", flush=True)
    asyncio.run(loop())
