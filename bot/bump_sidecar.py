import asyncio
import contextlib
import json
import os
import random
import signal
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
DISCORD_DESKTOP = os.getenv("DISCORD_DESKTOP_BIN") or next(
    (
        path
        for path in ("/opt/Discord/discord", "/opt/Discord/Discord")
        if os.path.isfile(path)
    ),
    "/opt/Discord/discord",
)
DISCORD_CONFIG_HOME = os.getenv(
    "DISCORD_CONFIG_HOME", "/var/lib/midvox/discord-home"
)
USER_PRESENCE_READY_FILE = os.getenv(
    "USER_PRESENCE_READY_FILE", "/tmp/midvox-user-presence-ready"
)


def nonce() -> str:
    return "".join(random.choices(string.digits, k=18))


async def validate_user_token(session: aiohttp.ClientSession) -> None:
    """Validate the token outside the Electron renderer.

    Renderer reloads can make an in-page fetch return an unrelated 400 even
    though the same token authenticated the desktop Gateway. A direct API
    check provides a stable startup signal instead.
    """
    async with session.get(
        f"{API_BASE}/users/@me",
        headers={"Authorization": TOKEN},
    ) as response:
        if response.status != 200:
            body = await response.text()
            raise RuntimeError(
                f"Discord user token validation HTTP {response.status}: "
                f"{body[:160]}"
            )


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


async def relay_desktop_output(stream):
    """Drain Discord output and retain useful startup diagnostics."""
    line_count = 0
    while True:
        line = await stream.readline()
        if not line:
            return
        line_count += 1
        text = line.decode("utf-8", errors="replace").strip()
        important = any(
            word in text.lower()
            for word in (
                "error",
                "fail",
                "install",
                "update",
                "module",
                "ready",
                "devtools",
                "version",
            )
        )
        if text and (line_count <= 80 or important):
            print(f"[discord-desktop] {text}", flush=True)


async def stop_desktop_process(process):
    """Stop the desktop bootstrapper and any children it launched."""
    if not process:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


async def discord_desktop_client():
    """Keep Discord's official desktop client open on a virtual display."""
    global SESSION_ID

    if not os.path.isfile(DISCORD_DESKTOP):
        raise RuntimeError("Discord desktop is missing from the container")

    async with aiohttp.ClientSession() as validation_session:
        await validate_user_token(validation_session)
    print("[discord-desktop] user token validated", flush=True)

    debug_port = 9222
    while True:
        display_process = None
        discord_process = None
        output_task = None
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
            desktop_environment["XDG_CONFIG_HOME"] = DISCORD_CONFIG_HOME
            desktop_environment["XDG_RUNTIME_DIR"] = "/tmp/midvox-runtime"
            os.makedirs(
                desktop_environment["XDG_RUNTIME_DIR"],
                mode=0o700,
                exist_ok=True,
            )
            print(
                "[discord-desktop] starting official client on virtual display :99",
                flush=True,
            )
            discord_process = await asyncio.create_subprocess_exec(
                "dbus-run-session",
                "--",
                DISCORD_DESKTOP,
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # SwiftShader creates an additional memory-heavy GPU process on
                # Railway. Discord's UI renders correctly with GPU composition
                # disabled, and this avoids short-lived renderer/GPU exits.
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-gpu-compositing",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--mute-audio",
                "--renderer-process-limit=2",
                f"--remote-debugging-port={debug_port}",
                "--user-data-dir=/tmp/midvox-discord-desktop",
                env=desktop_environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            output_task = asyncio.create_task(
                relay_desktop_output(discord_process.stdout)
            )

            async with aiohttp.ClientSession() as session:
                target = None
                exited_at = None
                for attempt in range(600):
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
                        # The official client first exposes a file:// updater
                        # splash target. Injecting into that target tears down the
                        # bootstrap and kills the browser. Wait for Discord's
                        # stable main application target instead.
                        target = next(
                            (
                                item
                                for item in pages
                                if any(
                                    origin in str(item.get("url") or "")
                                    for origin in (
                                        "discordapp.com/app",
                                        "discord.com/app",
                                    )
                                )
                            ),
                            None,
                        )
                        if target:
                            break
                    except (aiohttp.ClientError, ValueError):
                        pass
                    if discord_process.returncode is not None:
                        exited_at = exited_at if exited_at is not None else attempt
                        if attempt - exited_at >= 60:
                            raise RuntimeError(
                                "Discord desktop bootstrapper exited with code "
                                f"{discord_process.returncode} and no client started"
                            )
                    if attempt in (60, 180, 360):
                        print(
                            "[discord-desktop] still waiting for the main app "
                            "window to become ready",
                            flush=True,
                        )
                    await asyncio.sleep(0.5)
                if not target:
                    raise RuntimeError("Discord desktop DevTools did not become ready")

                # Let the initial login renderer finish before touching it.
                # Reloading Electron while splash/main boot is still active causes
                # Chromium exitCode=11. Reacquire the now-stable Discord target
                # after the delay rather than reusing the early /app target.
                await asyncio.sleep(8)
                try:
                    async with session.get(
                        f"http://127.0.0.1:{debug_port}/json/list"
                    ) as response:
                        targets = await response.json()
                    target = next(
                        (
                            item
                            for item in targets
                            if item.get("type") == "page"
                            and item.get("webSocketDebuggerUrl")
                            and any(
                                origin in str(item.get("url") or "")
                                for origin in (
                                    "discordapp.com/",
                                    "discord.com/",
                                )
                            )
                        ),
                        target,
                    )
                except (aiohttp.ClientError, ValueError):
                    pass

                # Inject the user token once, then completely detach DevTools.
                # Keeping a page-level CDP socket open interferes with Discord's
                # authentication transition and makes the sidecar kill a healthy
                # client whenever that target is replaced.
                token_literal = json.dumps(TOKEN)
                token_reused = False
                try:
                    async with session.ws_connect(
                        target["webSocketDebuggerUrl"]
                    ) as ws:
                        handoff = await cdp_call(
                            ws,
                            1,
                            "Runtime.evaluate",
                            {
                                # Reload only when the expected token is absent
                                # or changed. A normal sidecar restart must not
                                # disconnect an already authenticated Gateway.
                                "expression": (
                                    "(() => {"
                                    f"const token = {token_literal};"
                                    "const expected = JSON.stringify(token);"
                                    "const needsReload = "
                                    "localStorage.getItem('token') !== expected;"
                                    "const writeToken = () => {"
                                    "const frame = document.createElement('iframe');"
                                    "frame.style.display = 'none';"
                                    "document.body.appendChild(frame);"
                                    "frame.contentWindow.localStorage.setItem("
                                    "'token', expected);"
                                    "frame.remove();"
                                    "};"
                                    "if (needsReload) {"
                                    "writeToken();"
                                    "const timer = setInterval(writeToken, 50);"
                                    "setTimeout(() => clearInterval(timer), 2500);"
                                    "setTimeout(() => window.location.reload(), 500);"
                                    "}"
                                    "return !needsReload;"
                                    "})()"
                                ),
                                "returnByValue": True,
                            },
                        )
                        token_reused = bool(
                            handoff.get("result", {}).get("value")
                        )
                except asyncio.CancelledError:
                    raise
                except (aiohttp.ClientError, RuntimeError) as error:
                    # The token write can itself trigger the target hand-off,
                    # closing the socket before DevTools returns its response.
                    # The token was validated over REST immediately beforehand.
                    print(
                        "[discord-desktop] token handoff closed DevTools "
                        f"during transition: {error}",
                        flush=True,
                    )
                if token_reused:
                    print(
                        "[discord-desktop] existing authentication reused; "
                        "Gateway left uninterrupted",
                        flush=True,
                    )
                else:
                    print(
                        "[discord-desktop] token injected with one authentication "
                        "reload; leaving client attached to its own Gateway",
                        flush=True,
                    )

                # Do not attach to, navigate, or periodically probe the renderer.
                # Discord owns its own reconnects; only restart if Electron exits.
                while discord_process.returncode is None:
                    await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[discord-desktop] error: {error}", flush=True)
        finally:
            await stop_desktop_process(discord_process)
            if output_task:
                output_task.cancel()
                await asyncio.gather(output_task, return_exceptions=True)
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
                                    "os": "Linux",
                                    "browser": "Discord Client",
                                    "device": "",
                                    "system_locale": "en-US",
                                    "browser_user_agent": (
                                        "Mozilla/5.0 (X11; Linux x86_64) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/148.0.0.0 Safari/537.36"
                                    ),
                                    "browser_version": "148.0.0.0",
                                    "os_version": "6",
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
                    print("[user-presence] Gateway identified; waiting for READY", flush=True)
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
                                        with contextlib.suppress(OSError):
                                            with open(
                                                USER_PRESENCE_READY_FILE,
                                                "w",
                                                encoding="utf-8",
                                            ) as ready_file:
                                                ready_file.write(SESSION_ID)
                                        print(
                                            "[user-presence] ONLINE as Linux Desktop; "
                                            "Gateway session ready",
                                            flush=True,
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
                        with contextlib.suppress(OSError):
                            os.remove(USER_PRESENCE_READY_FILE)
                        heartbeat_task.cancel()
                        await asyncio.gather(heartbeat_task, return_exceptions=True)
        except Exception as e:
            print(f"[user-presence] error: {e}", flush=True)

        print("[user-presence] reconnecting in 5s", flush=True)
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


async def supervise(name, coroutine_factory):
    """Restart one sidecar component without stopping the other components."""
    while True:
        try:
            await coroutine_factory()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[{name}] crashed: {error}", flush=True)
        print(f"[{name}] restarting in 5s", flush=True)
        await asyncio.sleep(5)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("USER_TOKEN required")

    async def main():
        print(
            "[presence] enabled; bump="
            + (f"channel {CHANNEL_ID}" if CHANNEL_ID else "disabled (BUMP_CHANNEL_ID not set)"),
            flush=True,
        )
        # Start and verify the user-account presence before launching the desktop
        # client, /bump, or any application services.
        presence_task = asyncio.create_task(
            supervise("user-presence", connect_presence)
        )
        try:
            await asyncio.wait_for(SESSION_READY.wait(), timeout=60)
        except TimeoutError:
            presence_task.cancel()
            await asyncio.gather(presence_task, return_exceptions=True)
            raise RuntimeError("User account presence did not become ready")

        print(
            "[user-presence] ready; starting desktop and remaining sidecars",
            flush=True,
        )
        tasks = [
            presence_task,
            supervise("discord-desktop", discord_desktop_client),
        ]
        if CHANNEL_ID:
            tasks.append(supervise("bump", loop))
        await asyncio.gather(*tasks)

    asyncio.run(main())
