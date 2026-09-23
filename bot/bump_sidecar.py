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
DISCORD_HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
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


async def linked_spotify_token(session: aiohttp.ClientSession):
    """Get the temporary Spotify token that Discord issues to its own client."""
    async with session.get(
        f"{API_BASE}/users/@me/connections", headers=DISCORD_HEADERS
    ) as response:
        if response.status != 200:
            print(
                f"[spotify] Discord connections HTTP {response.status}",
                flush=True,
            )
            return None
        connections = await response.json()

    connection = next(
        (
            item
            for item in connections
            if isinstance(item, dict) and item.get("type") == "spotify"
        ),
        None,
    )
    if not connection or not connection.get("id"):
        print("[spotify] no linked Spotify connection", flush=True)
        return None

    connection_id = quote(str(connection["id"]), safe="")
    async with session.get(
        f"{API_BASE}/users/@me/connections/spotify/{connection_id}/access-token",
        headers=DISCORD_HEADERS,
    ) as response:
        if response.status != 200:
            print(
                f"[spotify] connection token HTTP {response.status}",
                flush=True,
            )
            return None
        data = await response.json()
    return data.get("access_token")


def spotify_activity_from_message(payload, discord_session_id, user_id):
    """Convert a Spotify dealer player update into a Discord activity."""
    for item in payload.get("payloads") or []:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except (TypeError, json.JSONDecodeError):
                continue
        if not isinstance(item, dict):
            continue

        cluster = item.get("cluster") or item
        player = cluster.get("player_state") if isinstance(cluster, dict) else None
        if not isinstance(player, dict):
            continue

        if not player.get("is_playing") or player.get("is_paused"):
            return True, None

        track = player.get("track") or {}
        metadata = track.get("metadata") or {}
        track_uri = str(track.get("uri") or "")
        title = str(metadata.get("title") or "Unknown track")
        artists = str(metadata.get("artist_name") or "Spotify")
        album = str(metadata.get("album_title") or "Spotify")
        image_uri = str(metadata.get("image_url") or "")
        image_id = image_uri.rsplit(":", 1)[-1] if image_uri else ""

        timestamp = int(player.get("timestamp") or time.time() * 1000)
        position = max(0, int(player.get("position_as_of_timestamp") or 0))
        duration = max(0, int(player.get("duration") or 0))
        start = timestamp - position

        activity = {
            "id": "spotify:1",
            "type": 2,
            "name": "Spotify",
            "details": title,
            "state": artists,
            "timestamps": {
                "start": start,
                "end": start + duration,
            },
            "assets": {
                "large_image": f"spotify:{image_id}" if image_id else "spotify",
                "large_text": album,
            },
            "party": {"id": f"spotify:{user_id}"},
            "sync_id": track_uri.rsplit(":", 1)[-1],
            "session_id": discord_session_id,
            "flags": 48,
            "created_at": timestamp,
        }
        return True, activity

    return False, None


async def spotify_ping(ws):
    """Keep Spotify's dealer websocket alive."""
    while not ws.closed:
        await ws.send_json({"type": "ping"})
        await asyncio.sleep(30)


async def spotify_realtime(discord_ws, discord_session_id, user_id):
    """Mirror linked phone playback using Discord's own Spotify connection."""
    last_activity = object()
    async with aiohttp.ClientSession() as session:
        while not discord_ws.closed and SESSION_ID == discord_session_id:
            ping_task = None
            try:
                token = await linked_spotify_token(session)
                if not token:
                    await asyncio.sleep(30)
                    continue

                dealer_url = (
                    "wss://dealer.spotify.com/?access_token="
                    f"{quote(str(token), safe='')}"
                )
                spotify_headers = {
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://open.spotify.com",
                    "User-Agent": DISCORD_HEADERS["User-Agent"],
                }
                async with session.ws_connect(
                    dealer_url,
                    headers={"Origin": "https://open.spotify.com"},
                    heartbeat=None,
                ) as spotify_ws:
                    ping_task = asyncio.create_task(spotify_ping(spotify_ws))
                    subscribed = False

                    async for message in spotify_ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(message.data)
                            except (TypeError, json.JSONDecodeError):
                                continue

                            message_headers = payload.get("headers") or {}
                            connection_id = message_headers.get(
                                "Spotify-Connection-Id"
                            ) or message_headers.get("spotify-connection-id")
                            if connection_id and not subscribed:
                                subscribe_url = (
                                    "https://api.spotify.com/v1/me/notifications/player"
                                    f"?connection_id={quote(str(connection_id), safe='')}"
                                )
                                async with session.put(
                                    subscribe_url, headers=spotify_headers
                                ) as response:
                                    if response.status not in (200, 204):
                                        raise RuntimeError(
                                            "Spotify player subscription HTTP "
                                            f"{response.status}"
                                        )
                                subscribed = True
                                print(
                                    "[spotify] realtime phone playback connected",
                                    flush=True,
                                )

                            found, activity = spotify_activity_from_message(
                                payload, discord_session_id, user_id
                            )
                            if not found:
                                continue

                            signature = json.dumps(activity, sort_keys=True)
                            if signature == last_activity:
                                continue
                            await discord_ws.send_json(
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
                            last_activity = signature
                            if activity:
                                print(
                                    f"[spotify] showing {activity['details']} — "
                                    f"{activity['state']}",
                                    flush=True,
                                )
                            else:
                                print("[spotify] playback stopped", flush=True)
                        elif message.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"[spotify] realtime error: {error}", flush=True)
            finally:
                if ping_task:
                    ping_task.cancel()
                    await asyncio.gather(ping_task, return_exceptions=True)

            if not discord_ws.closed and SESSION_ID == discord_session_id:
                await asyncio.sleep(5)


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
                                "capabilities": 4093,
                                "properties": {
                                    "os": "Windows",
                                    "browser": "Discord Client",
                                    "device": "",
                                    "system_locale": "en-US",
                                    "browser_user_agent": (
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/124.0.0.0 Safari/537.36"
                                    ),
                                    "browser_version": "124.0.0.0",
                                    "os_version": "10",
                                    "referrer": "",
                                    "referring_domain": "",
                                },
                                "presence": {
                                    "status": "online",
                                    "since": 0,
                                    "activities": [],
                                    "afk": False,
                                },
                                "compress": False,
                                "client_state": {
                                    "guild_versions": {},
                                    "highest_last_message_id": "0",
                                    "read_state_version": 0,
                                    "user_guild_settings_version": -1,
                                    "user_settings_version": -1,
                                    "private_channels_version": "0",
                                    "api_code_version": 0,
                                },
                            },
                        }
                    )

                    heartbeat_task = asyncio.create_task(heartbeat(ws, interval, sequence))
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
                                        user_id = str(
                                            payload.get("d", {}).get("user", {}).get("id")
                                            or ""
                                        )
                                        if user_id and spotify_task is None:
                                            spotify_task = asyncio.create_task(
                                                spotify_realtime(ws, SESSION_ID, user_id)
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
                        if spotify_task:
                            spotify_task.cancel()
                        await asyncio.gather(
                            heartbeat_task,
                            *((spotify_task,) if spotify_task else ()),
                            return_exceptions=True,
                        )
        except Exception as e:
            print(f"[bump] presence error: {e}", flush=True)

        print("[bump] reconnecting user presence in 5s", flush=True)
        await asyncio.sleep(5)


async def loop():
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyMzgxNiwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=",
    }
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
