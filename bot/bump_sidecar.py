import asyncio
import json
import os
import random
import string
import time
from urllib.parse import quote

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
SESSION_ID = ""
SESSION_READY = asyncio.Event()
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SUPER_PROPERTIES = "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyMzgxNiwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0="
DISCORD_HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
    "X-Super-Properties": SUPER_PROPERTIES,
}


def nonce() -> str:
    return "".join(random.choices(string.digits, k=18))


async def fetch_bump_command(session: aiohttp.ClientSession, headers: dict, guild_id: str):
    # Query DISBOARD directly first, then fall back to the complete guild index.
    # The channel index can contain unrelated user-installed applications.
    urls = [
        f"{API_BASE}/applications/{DISBOARD_APP_ID}/application-command-index",
        f"{API_BASE}/guilds/{guild_id}/application-command-index",
    ]
    for url in urls:
        async with session.get(url, headers=headers) as r:
            body = await r.text()
            source = "DISBOARD" if f"applications/{DISBOARD_APP_ID}" in url else "guild"
            print(f"[bump] {source} command index HTTP {r.status}", flush=True)
            if r.status != 200:
                continue
            try:
                data = json.loads(body)
            except Exception:
                print(f"[bump] {source} command index returned invalid JSON", flush=True)
                continue

            cmds = data.get("application_commands") or data.get("commands") or []
            if isinstance(cmds, dict):
                cmds = list(cmds.values())
            for c in cmds:
                if not isinstance(c, dict):
                    continue
                application_id = str(c.get("application_id") or DISBOARD_APP_ID)
                if (
                    application_id == DISBOARD_APP_ID
                    and c.get("name") == "bump"
                    and int(c.get("type") or 1) == 1
                ):
                    print(
                        f"[bump] selected DISBOARD /bump id={c['id']} "
                        f"application={application_id}",
                        flush=True,
                    )
                    return c
            print(f"[bump] {source} index had {len(cmds)} commands; DISBOARD /bump absent", flush=True)
    return None


async def send_bump(session: aiohttp.ClientSession, headers: dict) -> None:
    if not SESSION_ID:
        try:
            await asyncio.wait_for(SESSION_READY.wait(), timeout=30)
        except TimeoutError:
            print("[bump] gateway session not ready; delaying bump", flush=True)
            return

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
        print("[bump] /bump not found — Disboard not in this guild/channel or still down", flush=True)
        return

    payload = {
        "type": 2,
        "application_id": DISBOARD_APP_ID,
        "guild_id": str(guild_id),
        "channel_id": str(CHANNEL_ID),
        "session_id": SESSION_ID,
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


async def heartbeat(ws, interval, sequence):
    """Keep the user session alive until the gateway connection closes."""
    await asyncio.sleep(interval)
    while not ws.closed:
        await ws.send_json({"op": 1, "d": sequence[0]})
        await asyncio.sleep(interval)


async def linked_spotify_token(session):
    """Use the existing Discord connection to obtain its Spotify access token."""
    async with session.get(
        f"{API_BASE}/users/@me/connections", headers=DISCORD_HEADERS
    ) as response:
        if response.status != 200:
            print(f"[spotify] Discord connections HTTP {response.status}", flush=True)
            return ""
        connections = await response.json()

    spotify = next(
        (
            connection
            for connection in connections
            if isinstance(connection, dict) and connection.get("type") == "spotify"
        ),
        None,
    )
    if not spotify or not spotify.get("id"):
        print("[spotify] no Spotify account is connected to this Discord user", flush=True)
        return ""

    connection_id = quote(str(spotify["id"]), safe="")
    url = f"{API_BASE}/users/@me/connections/spotify/{connection_id}/access-token"
    async with session.get(url, headers=DISCORD_HEADERS) as response:
        if response.status != 200:
            print(f"[spotify] connection token HTTP {response.status}", flush=True)
            return ""
        data = await response.json()
    return str(data.get("access_token") or "")


def spotify_activity(playback, session_id):
    """Convert Spotify's currently-playing response into Discord activity data."""
    item = playback.get("item") if isinstance(playback, dict) else None
    if not playback.get("is_playing") or not isinstance(item, dict):
        return None

    timestamp = int(playback.get("timestamp") or time.time() * 1000)
    progress = int(playback.get("progress_ms") or 0)
    duration = int(item.get("duration_ms") or 0)
    started = timestamp - progress

    artists = item.get("artists") or []
    artist_names = "; ".join(
        str(artist.get("name"))
        for artist in artists
        if isinstance(artist, dict) and artist.get("name")
    )
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    assets = {"large_text": str(album.get("name") or "Spotify")}
    images = album.get("images") or []
    if images and isinstance(images[0], dict):
        image_url = str(images[0].get("url") or "")
        if "/image/" in image_url:
            assets["large_image"] = f"spotify:{image_url.rsplit('/image/', 1)[-1]}"

    activity = {
        "type": 2,
        "name": "Spotify",
        "details": str(item.get("name") or "Unknown track"),
        "state": artist_names or "Spotify",
        "timestamps": {"start": started, "end": started + duration},
        "assets": assets,
        "sync_id": str(item.get("id") or ""),
        "session_id": session_id,
        "flags": 48,
        "created_at": timestamp,
    }
    return activity


async def spotify_presence_loop(ws, session_id):
    """Publish linked Spotify playback without needing a local Discord client."""
    access_token = ""
    refresh_at = 0.0
    last_track = object()

    async with aiohttp.ClientSession() as session:
        while not ws.closed and SESSION_ID == session_id:
            try:
                if not access_token or time.monotonic() >= refresh_at:
                    access_token = await linked_spotify_token(session)
                    if not access_token:
                        await asyncio.sleep(60)
                        continue
                    refresh_at = time.monotonic() + 25 * 60
                    print("[spotify] linked account token ready", flush=True)

                async with session.get(
                    "https://api.spotify.com/v1/me/player/currently-playing",
                    headers={"Authorization": f"Bearer {access_token}"},
                ) as response:
                    if response.status == 204:
                        playback = {}
                    elif response.status == 401:
                        access_token = ""
                        refresh_at = 0.0
                        await asyncio.sleep(5)
                        continue
                    elif response.status == 429:
                        await asyncio.sleep(float(response.headers.get("Retry-After", "15")))
                        continue
                    elif response.status != 200:
                        print(f"[spotify] currently playing HTTP {response.status}", flush=True)
                        await asyncio.sleep(30)
                        continue
                    else:
                        playback = await response.json()

                activity = spotify_activity(playback, session_id)
                track_key = activity.get("sync_id") if activity else None
                if track_key != last_track:
                    await ws.send_json(
                        {
                            "op": 3,
                            "d": {
                                "since": 0,
                                "activities": [activity] if activity else [],
                                "status": "online",
                                "afk": False,
                            },
                        }
                    )
                    last_track = track_key
                    if activity:
                        print(
                            f"[spotify] showing {activity['details']} — {activity['state']}",
                            flush=True,
                        )
                    else:
                        print("[spotify] playback stopped; activity cleared", flush=True)
            except Exception as error:
                print(f"[spotify] update error: {error}", flush=True)

            await asyncio.sleep(15)


async def connect_presence():
    """Maintain a Discord gateway session so the account appears online."""
    global SESSION_ID

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(GATEWAY, heartbeat=None) as ws:
                    hello = await ws.receive_json()
                    if hello.get("op") != 10:
                        raise RuntimeError("Discord gateway did not send HELLO")

                    interval = hello["d"]["heartbeat_interval"] / 1000
                    sequence = [None]
                    await ws.send_json(
                        {
                            "op": 2,
                            "d": {
                                "token": TOKEN,
                                "properties": {
                                    "os": "Windows",
                                    "browser": "Discord Client",
                                    "device": "",
                                },
                                "presence": {
                                    "status": "online",
                                    "since": 0,
                                    "activities": [],
                                    "afk": False,
                                },
                                "compress": False,
                            },
                        }
                    )

                    heartbeat_task = asyncio.create_task(
                        heartbeat(ws, interval, sequence)
                    )
                    spotify_task = None
                    print("[bump] gateway identified; waiting for READY", flush=True)
                    try:
                        async for message in ws:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                if payload.get("s") is not None:
                                    sequence[0] = payload["s"]
                                if payload.get("op") == 0 and payload.get("t") == "READY":
                                    SESSION_ID = str(payload.get("d", {}).get("session_id") or "")
                                    if SESSION_ID:
                                        SESSION_READY.set()
                                        print("[bump] user presence online and session ready", flush=True)
                                        if spotify_task is None:
                                            spotify_task = asyncio.create_task(
                                                spotify_presence_loop(ws, SESSION_ID)
                                            )
                                if payload.get("op") == 1:
                                    await ws.send_json({"op": 1, "d": sequence[0]})
                                elif payload.get("op") in (7, 9):
                                    break
                            elif message.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                    finally:
                        SESSION_ID = ""
                        SESSION_READY.clear()
                        heartbeat_task.cancel()
                        if spotify_task is not None:
                            spotify_task.cancel()
                        await asyncio.gather(
                            heartbeat_task,
                            *([spotify_task] if spotify_task is not None else []),
                            return_exceptions=True,
                        )
        except Exception as e:
            print(f"[bump] presence error: {e}", flush=True)

        print("[bump] reconnecting user presence in 5s", flush=True)
        await asyncio.sleep(5)


async def loop():
    headers = dict(DISCORD_HEADERS)
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s", flush=True)
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

    async def main():
        await asyncio.gather(loop(), connect_presence())

    asyncio.run(main())
