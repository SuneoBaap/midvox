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
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
SESSION_ID = ""
SESSION_READY = asyncio.Event()


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


def listening_activities(sessions, current_session_id):
    """Return unique listening activities reported by another user session."""
    mirrored = []
    seen = set()
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id") or "")
        for activity in session.get("activities") or []:
            if not isinstance(activity, dict) or int(activity.get("type") or 0) != 2:
                continue

            source_session = str(activity.get("session_id") or session_id)
            if source_session == current_session_id:
                continue

            outgoing = {
                key: value
                for key, value in activity.items()
                if key not in {"id", "session_id"} and value is not None
            }
            signature = json.dumps(outgoing, sort_keys=True, separators=(",", ":"))
            if signature not in seen:
                seen.add(signature)
                mirrored.append(outgoing)
    return mirrored


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
                                    "os": "windows",
                                    "browser": "Chrome",
                                    "device": "Chrome",
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
                    mirrored_signature = None
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
                                elif payload.get("op") == 0 and payload.get("t") == "SESSIONS_REPLACE":
                                    activities = listening_activities(payload.get("d"), SESSION_ID)
                                    signature = json.dumps(
                                        activities, sort_keys=True, separators=(",", ":")
                                    )
                                    if signature != mirrored_signature:
                                        await ws.send_json(
                                            {
                                                "op": 3,
                                                "d": {
                                                    "since": 0,
                                                    "activities": activities,
                                                    "status": "online",
                                                    "afk": False,
                                                },
                                            }
                                        )
                                        mirrored_signature = signature
                                        if activities:
                                            song = activities[0].get("details") or activities[0].get("name")
                                            print(f"[bump] mirrored listening activity: {song}", flush=True)
                                        else:
                                            print("[bump] no external listening activity", flush=True)
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
                        await asyncio.gather(heartbeat_task, return_exceptions=True)
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
