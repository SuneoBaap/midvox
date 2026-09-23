import asyncio
import json
import os
import random
import string

import aiohttp

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
SESSION_ID = ""
SESSION_READY = asyncio.Event()
DISCORD_DESKTOP = os.getenv("DISCORD_DESKTOP_BIN", "/opt/Discord/Discord")


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


async def cdp_call(ws, request_id, method, params=None):
    """Send one Chrome DevTools command and wait for its response."""
    payload = {"id": request_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send_json(payload)
    while True:
        message = await ws.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Discord desktop DevTools connection closed")
        response = json.loads(message.data)
        if response.get("id") != request_id:
            continue
        if response.get("error"):
            raise RuntimeError(response["error"].get("message") or "DevTools error")
        return response.get("result") or {}


async def discord_desktop_client():
    """Keep Discord's official desktop client open on a virtual display."""
    if not os.path.isfile(DISCORD_DESKTOP):
        raise RuntimeError("Discord desktop is missing from the container")

    debug_port = 9222
    while True:
        display_process = None
        discord_process = None
        try:
            display_process = await asyncio.create_subprocess_exec(
                "Xvfb",
                ":99",
                "-screen",
                "0",
                "1280x720x24",
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(1)
            if display_process.returncode is not None:
                raise RuntimeError(
                    f"Xvfb exited with code {display_process.returncode}"
                )

            desktop_environment = os.environ.copy()
            desktop_environment["DISPLAY"] = ":99"
            discord_process = await asyncio.create_subprocess_exec(
                DISCORD_DESKTOP,
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--mute-audio",
                "--renderer-process-limit=2",
                f"--remote-debugging-port={debug_port}",
                "--user-data-dir=/tmp/midvox-discord-desktop",
                env=desktop_environment,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            async with aiohttp.ClientSession() as session:
                target = None
                for _ in range(60):
                    if discord_process.returncode is not None:
                        raise RuntimeError(
                            "Discord desktop exited with code "
                            f"{discord_process.returncode}"
                        )
                    try:
                        async with session.get(
                            f"http://127.0.0.1:{debug_port}/json/list"
                        ) as response:
                            targets = await response.json()
                        pages = [
                            item
                            for item in targets
                            if item.get("type") == "page"
                            and item.get("webSocketDebuggerUrl")
                        ]
                        target = next(
                            (
                                item
                                for item in pages
                                if "discord.com" in str(item.get("url") or "")
                            ),
                            pages[0] if pages else None,
                        )
                        if target:
                            break
                    except (aiohttp.ClientError, ValueError):
                        pass
                    await asyncio.sleep(0.5)
                if not target:
                    raise RuntimeError("Discord desktop DevTools did not become ready")

                async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                    await cdp_call(ws, 1, "Page.enable")
                    await cdp_call(
                        ws,
                        2,
                        "Page.addScriptToEvaluateOnNewDocument",
                        {
                            "source": (
                                "Object.defineProperty(navigator, 'webdriver', "
                                "{get: () => undefined});"
                            )
                        },
                    )
                    await cdp_call(
                        ws,
                        3,
                        "Page.navigate",
                        {"url": "https://discord.com/login"},
                    )
                    await asyncio.sleep(8)

                    token_literal = json.dumps(TOKEN)
                    await cdp_call(
                        ws,
                        4,
                        "Runtime.evaluate",
                        {
                            "expression": (
                                "(() => {"
                                f"const token = {token_literal};"
                                "const writeToken = () => {"
                                "const frame = document.createElement('iframe');"
                                "frame.style.display = 'none';"
                                "document.body.appendChild(frame);"
                                "frame.contentWindow.localStorage.setItem("
                                "'token', JSON.stringify(token));"
                                "frame.remove();"
                                "};"
                                "writeToken();"
                                "const timer = setInterval(writeToken, 50);"
                                "setTimeout(() => clearInterval(timer), 2500);"
                                "return true;"
                                "})()"
                            ),
                            "returnByValue": True,
                        },
                    )
                    await asyncio.sleep(3)
                    stored = await cdp_call(
                        ws,
                        5,
                        "Runtime.evaluate",
                        {
                            "expression": (
                                "(() => {"
                                "const frame = document.createElement('iframe');"
                                "frame.style.display = 'none';"
                                "document.body.appendChild(frame);"
                                "const value = frame.contentWindow.localStorage."
                                "getItem('token');"
                                "frame.remove();"
                                f"return value === JSON.stringify({token_literal});"
                                "})()"
                            ),
                            "returnByValue": True,
                        },
                    )
                    if not stored.get("result", {}).get("value"):
                        raise RuntimeError("Discord token was not stored by desktop")

                    auth_check = await cdp_call(
                        ws,
                        6,
                        "Runtime.evaluate",
                        {
                            "expression": (
                                "fetch('/api/v10/users/@me', {headers: "
                                f"{{Authorization: {token_literal}}}}})"
                                ".then(response => response.status)"
                            ),
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                    )
                    auth_status = auth_check.get("result", {}).get("value")
                    if auth_status != 200:
                        raise RuntimeError(
                            f"Discord desktop authentication HTTP {auth_status}"
                        )

                    await cdp_call(
                        ws,
                        7,
                        "Page.navigate",
                        {"url": "https://discord.com/channels/@me"},
                    )

                    request_id = 8
                    browser_url = ""
                    for _ in range(9):
                        await asyncio.sleep(5)
                        status = await cdp_call(
                            ws,
                            request_id,
                            "Runtime.evaluate",
                            {
                                "expression": (
                                    "JSON.stringify({href: location.href, "
                                    "ready: document.readyState})"
                                ),
                                "returnByValue": True,
                            },
                        )
                        request_id += 1
                        status_value = (
                            status.get("result", {}).get("value") or "{}"
                        )
                        browser_state = json.loads(status_value)
                        browser_url = browser_state.get("href") or ""
                        if browser_url and "/login" not in browser_url:
                            break

                    if not browser_url or "/login" in browser_url:
                        raise RuntimeError(
                            "Discord desktop stayed on the login page"
                        )
                    print(
                        "[discord-desktop] client running at "
                        f"{browser_url or 'https://discord.com/app'}",
                        flush=True,
                    )

                    while discord_process.returncode is None:
                        await asyncio.sleep(60)
                        await cdp_call(
                            ws,
                            request_id,
                            "Runtime.evaluate",
                            {
                                "expression": "document.readyState",
                                "returnByValue": True,
                            },
                        )
                        request_id += 1
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[discord-desktop] error: {error}", flush=True)
        finally:
            if discord_process and discord_process.returncode is None:
                discord_process.terminate()
                try:
                    await asyncio.wait_for(discord_process.wait(), timeout=5)
                except TimeoutError:
                    discord_process.kill()
                    await discord_process.wait()
            if display_process and display_process.returncode is None:
                display_process.terminate()
                try:
                    await asyncio.wait_for(display_process.wait(), timeout=5)
                except TimeoutError:
                    display_process.kill()
                    await display_process.wait()

        print("[discord-desktop] restarting client in 5s", flush=True)
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
        await asyncio.gather(loop(), connect_presence(), discord_desktop_client())

    asyncio.run(main())
