import asyncio
import contextlib
import glob
import json
import os
import random
import signal
import string

import aiohttp

from presence_mirror import (
    activities_signature,
    mirrorable_session_activities,
    normalize_presence_activities,
)

TOKEN = os.environ.get("USER_TOKEN", "")
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "")
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
SESSION_ID = ""
SESSION_READY = asyncio.Event()
ONLINE_REFRESH_SECONDS = 240
DESKTOP_WAKE_SECONDS = 240
DISCORD_DESKTOP = os.getenv("DISCORD_DESKTOP_BIN") or next(
    iter(
        sorted(
            glob.glob("/var/lib/midvox/discord-home/discord/app-*/Discord"),
            reverse=True,
        )
        + [
            path
            for path in ("/opt/Discord/Discord", "/opt/Discord/discord")
            if os.path.isfile(path)
        ]
    ),
    "/opt/Discord/discord",
)
DISCORD_CONFIG_HOME = os.getenv(
    "DISCORD_CONFIG_HOME", "/var/lib/midvox/discord-home"
)
USER_DESKTOP_READY_FILE = os.getenv(
    "USER_DESKTOP_READY_FILE", "/tmp/midvox-user-desktop-ready"
)
# Readiness marker for the Linux Desktop Gateway fallback.
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


async def publish_online(ws, activities):
    """Publish an explicit online presence without creating channel noise."""
    await ws.send_json(
        {
            "op": 3,
            "d": {
                "status": "online",
                "since": 0,
                "activities": activities,
                "afk": False,
            },
        }
    )


async def keep_online(ws, activities):
    """Refresh the user presence every four minutes to prevent idle status."""
    while not ws.closed:
        await asyncio.sleep(ONLINE_REFRESH_SECONDS)
        await publish_online(ws, activities())
        print("[user-presence] refreshed online status", flush=True)


async def cdp_call(ws, request_id, method, params=None):
    """Send one Chrome DevTools command and wait for its response."""
    payload = {"id": request_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send_json(payload)
    while True:
        message = await asyncio.wait_for(ws.receive(), timeout=20)
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Discord desktop DevTools connection closed")
        response = json.loads(message.data)
        if response.get("id") != request_id:
            continue
        if response.get("error"):
            raise RuntimeError(response["error"].get("message") or "DevTools error")
        result = response.get("result") or {}
        if result.get("exceptionDetails"):
            # Never echo evaluated source: a login expression may contain a secret.
            raise RuntimeError("Discord desktop JavaScript evaluation failed")
        return result


async def authenticate_desktop(session, target, debug_port):
    """Move the settled target to discord.com and hand it the user token."""
    try:
        async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
            await cdp_call(
                ws,
                1,
                "Page.navigate",
                {"url": "https://discord.com/login"},
            )
    except (aiohttp.ClientError, RuntimeError) as error:
        print(
            "[discord-desktop] login-origin navigation transition: "
            f"{error}",
            flush=True,
        )

    await asyncio.sleep(5)
    async with session.get(f"http://127.0.0.1:{debug_port}/json/list") as response:
        targets = await response.json()
    pages = [
        item
        for item in targets
        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
    ]
    target = next(
        (
            item
            for item in pages
            if str(item.get("url") or "").startswith("https://discord.com/")
        ),
        None,
    )
    if not target:
        raise RuntimeError("discord.com login target did not become available")

    async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
        storage_id = {"securityOrigin": "https://discord.com", "isLocalStorage": True}
        # Discord removes window.localStorage from the page. Write through CDP
        # rather than evaluating JavaScript against that missing global.
        await cdp_call(
            ws,
            2,
            "DOMStorage.setDOMStorageItem",
            {
                "storageId": storage_id,
                "key": "token",
                "value": json.dumps(TOKEN),
            },
        )
        stored = await cdp_call(
            ws, 3, "DOMStorage.getDOMStorageItems", {"storageId": storage_id}
        )
        if dict(stored.get("entries", [])).get("token") != json.dumps(TOKEN):
            raise RuntimeError("Discord desktop credential storage verification failed")
        # Reload lets the client consume the stored credential during startup.
        # Success here is only a handoff; Gateway READY is checked separately.
        await cdp_call(ws, 4, "Page.reload", {})
    return False


async def wake_desktop_in_bump_channel(session, debug_port):
    """Create and erase one character in the bump channel without sending it."""
    if not CHANNEL_ID:
        return

    async with session.get(
        f"{API_BASE}/channels/{CHANNEL_ID}",
        headers={"Authorization": TOKEN},
    ) as response:
        if response.status != 200:
            raise RuntimeError(
                f"bump channel lookup returned HTTP {response.status}"
            )
        guild_id = str((await response.json()).get("guild_id") or "")
    if not guild_id:
        raise RuntimeError("bump channel is not attached to a guild")

    async with session.get(f"http://127.0.0.1:{debug_port}/json/list") as response:
        targets = await response.json()
    target = next(
        (
            item
            for item in targets
            if item.get("type") == "page"
            and str(item.get("url") or "").startswith("https://discord.com/")
            and item.get("webSocketDebuggerUrl")
        ),
        None,
    )
    if not target:
        raise RuntimeError("Discord desktop page is unavailable")

    async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
        await cdp_call(
            ws,
            1,
            "Page.navigate",
            {"url": f"https://discord.com/channels/{guild_id}/{CHANNEL_ID}"},
        )
        await asyncio.sleep(3)
        focused = await cdp_call(
            ws,
            2,
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => { const box = document.querySelector("
                    "'[role=\"textbox\"][contenteditable=\"true\"]'); "
                    "if (!box) return false; box.focus(); return true; })()"
                ),
                "returnByValue": True,
            },
        )
        if not focused.get("result", {}).get("value"):
            raise RuntimeError("Discord message box did not become available")
        await cdp_call(ws, 3, "Input.insertText", {"text": "."})
        await cdp_call(
            ws,
            4,
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "Backspace",
                "code": "Backspace",
                "windowsVirtualKeyCode": 8,
                "nativeVirtualKeyCode": 8,
            },
        )
        await cdp_call(
            ws,
            5,
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Backspace",
                "code": "Backspace",
                "windowsVirtualKeyCode": 8,
                "nativeVirtualKeyCode": 8,
            },
        )


async def keep_desktop_active(session, debug_port):
    """Wake Discord periodically so linked activities continue updating."""
    await asyncio.sleep(30)
    while True:
        try:
            await wake_desktop_in_bump_channel(session, debug_port)
            print(
                "[discord-desktop] bump-channel activity refreshed; no message sent",
                flush=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[discord-desktop] activity refresh failed: {error}", flush=True)
        await asyncio.sleep(DESKTOP_WAKE_SECONDS)


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
        if "[GatewaySocket] [READY]" in text:
            with contextlib.suppress(OSError):
                with open(
                    USER_DESKTOP_READY_FILE,
                    "w",
                    encoding="utf-8",
                ) as ready_file:
                    ready_file.write("ready")
            print(
                "[user-desktop] ONLINE as Linux Desktop; official Gateway READY",
                flush=True,
            )


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


def desktop_process_group_alive(process) -> bool:
    """Return whether any process from the launched desktop session remains.

    Discord may close its DevTools listener or let its launcher process exit
    while the detached Electron client and Gateway remain healthy.  Every
    process inherits the new session/process group created at launch, making
    the group the durable lifecycle signal.
    """
    if not process:
        return False
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
        with contextlib.suppress(OSError):
            os.remove(USER_DESKTOP_READY_FILE)
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
                # Chromium exitCode=11.
                await asyncio.sleep(8)
                if os.path.isfile(USER_DESKTOP_READY_FILE):
                    print(
                        "[discord-desktop] authenticated Gateway already ready; "
                        "authentication handoff skipped",
                        flush=True,
                    )
                else:
                    try:
                        token_reused = await authenticate_desktop(
                            session,
                            target,
                            debug_port,
                        )
                    except asyncio.CancelledError:
                        raise
                    except (aiohttp.ClientError, RuntimeError, ValueError) as error:
                        raise RuntimeError("Desktop authentication handoff failed") from error
                    if token_reused:
                        print(
                            "[discord-desktop] existing discord.com authentication "
                            "reused",
                            flush=True,
                        )
                    else:
                        print(
                            "[discord-desktop] token written on discord.com; "
                            "waiting for authenticated Gateway READY",
                            flush=True,
                        )

                activity_task = asyncio.create_task(
                    keep_desktop_active(session, debug_port)
                )
                try:
                    # Discord can detach from its launcher and can close the
                    # optional DevTools listener while its Gateway stays ready.
                    # The inherited process group covers the actual Electron
                    # client and is the reliable lifecycle signal.
                    while desktop_process_group_alive(discord_process):
                        await asyncio.sleep(30)
                    raise RuntimeError("Discord desktop process group exited")
                finally:
                    activity_task.cancel()
                    await asyncio.gather(activity_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[discord-desktop] error: {error}", flush=True)
        finally:
            with contextlib.suppress(OSError):
                os.remove(USER_DESKTOP_READY_FILE)
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
                                    # Ask Discord to assign the initial presence,
                                    # then publish online plus any local-PC
                                    # activity after READY.
                                    "status": "unknown",
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
                    mirrored_signature = None
                    mirrored_activities = []
                    current_user_id = ""
                    print("[user-presence] Gateway identified; waiting for READY", flush=True)

                    async def publish_mirrored_presence(source, data):
                        nonlocal mirrored_activities, mirrored_signature
                        mirrored = mirrorable_session_activities(data, SESSION_ID)
                        signature = activities_signature(mirrored)
                        if mirrored_signature is not None and signature == mirrored_signature:
                            return
                        # Re-apply presence after READY. Some Discord routing
                        # paths ignore the presence embedded in Identify until
                        # a separate OP3 Presence Update arrives.
                        await publish_online(ws, mirrored)
                        mirrored_activities = mirrored
                        mirrored_signature = signature
                        print(
                            "[user-presence] Sent online presence with "
                            f"{len(mirrored)} mirrored activities from {source}",
                            flush=True,
                        )

                    online_task = asyncio.create_task(
                        keep_online(ws, lambda: mirrored_activities)
                    )
                    try:
                        async for message in ws:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                if payload.get("s") is not None:
                                    sequence[0] = payload["s"]
                                if payload.get("op") == 0 and payload.get("t") == "READY":
                                    SESSION_ID = str(payload.get("d", {}).get("session_id") or "")
                                    current_user_id = str(
                                        payload.get("d", {})
                                        .get("user", {})
                                        .get("id")
                                        or ""
                                    )
                                    if SESSION_ID:
                                        await publish_mirrored_presence(
                                            "READY", payload.get("d", {})
                                        )
                                        with contextlib.suppress(OSError):
                                            with open(
                                                USER_PRESENCE_READY_FILE,
                                                "w",
                                                encoding="utf-8",
                                            ) as ready_file:
                                                ready_file.write(SESSION_ID)
                                        SESSION_READY.set()
                                elif (
                                    payload.get("op") == 0
                                    and payload.get("t") == "SESSIONS_REPLACE"
                                ):
                                    await publish_mirrored_presence(
                                        "SESSIONS_REPLACE", payload.get("d", [])
                                    )
                                elif (
                                    payload.get("op") == 0
                                    and payload.get("t") == "PRESENCE_UPDATE"
                                    and current_user_id
                                    and str(
                                        payload.get("d", {})
                                        .get("user", {})
                                        .get("id")
                                        or ""
                                    )
                                    == current_user_id
                                ):
                                    # Discord emits self presence changes sooner
                                    # than its batched session replacement event.
                                    # This path updates play, pause, and track
                                    # changes as soon as the Gateway reports them.
                                    immediate = normalize_presence_activities(
                                        payload.get("d", {}).get("activities", [])
                                    )
                                    signature = activities_signature(immediate)
                                    if signature != mirrored_signature:
                                        await publish_online(ws, immediate)
                                        mirrored_activities = immediate
                                        mirrored_signature = signature
                                        print(
                                            "[user-presence] Sent immediate activity "
                                            "update from PRESENCE_UPDATE",
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
                        online_task.cancel()
                        await asyncio.gather(
                            heartbeat_task,
                            online_task,
                            return_exceptions=True,
                        )
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
        # The official desktop carries connected Spotify activity. A lightweight
        # companion Gateway session supplies /bump's session ID and refreshes
        # the online presence every four minutes.
        desktop_task = asyncio.create_task(
            supervise("discord-desktop", discord_desktop_client)
        )
        for _ in range(60):
            if os.path.isfile(USER_DESKTOP_READY_FILE):
                break
            if desktop_task.done():
                await desktop_task
            await asyncio.sleep(0.5)

        presence_task = asyncio.create_task(
            supervise("user-presence", connect_presence)
        )
        try:
            await asyncio.wait_for(SESSION_READY.wait(), timeout=45)
        except TimeoutError:
            presence_task.cancel()
            desktop_task.cancel()
            await asyncio.gather(
                presence_task,
                desktop_task,
                return_exceptions=True,
            )
            raise RuntimeError("User-account presence session failed")

        if os.path.isfile(USER_DESKTOP_READY_FILE):
            print(
                "[user-desktop] official Gateway ready; four-minute online "
                "refresh active",
                flush=True,
            )
        else:
            print(
                "[user-desktop] official client is still starting; online "
                "presence refresh is active",
                flush=True,
            )

        tasks = [desktop_task, presence_task]
        if CHANNEL_ID:
            tasks.append(supervise("bump", loop))
        await asyncio.gather(*tasks)

    asyncio.run(main())
