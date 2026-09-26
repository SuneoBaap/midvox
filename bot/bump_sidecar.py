import asyncio
import contextlib
import json
import os
import random
import signal
import string
import time

import aiohttp

from presence_mirror import (
    activities_signature,
    mirrorable_session_activities,
    summarize_activities,
)
from gateway_resume import (
    AUTH_FAILED_CLOSE_CODES,
    INITIAL_BACKOFF,
    next_backoff,
    should_resume,
)

TOKEN = os.environ.get("USER_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("BUMP_CHANNEL_ID", "").strip()
INTERVAL = int(os.getenv("BUMP_INTERVAL", "600"))
DISBOARD_APP_ID = "302050872383242240"
API_BASE = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
SESSION_ID = ""
SESSION_READY = asyncio.Event()
RESUME_GATEWAY_URL = GATEWAY
RESUME_SESSION_ID = ""
RESUME_SEQ = None
RECONNECT_DELAY = INITIAL_BACKOFF
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
USER_DESKTOP_READY_FILE = os.getenv(
    "USER_DESKTOP_READY_FILE", "/tmp/midvox-user-desktop-ready"
)
# Readiness marker for the lightweight user Gateway (sole presence path).
USER_PRESENCE_READY_FILE = os.getenv(
    "USER_PRESENCE_READY_FILE", "/tmp/midvox-user-presence-ready"
)
# Latched presence (real Spotify details etc.) persisted across restarts so
# music keeps showing permanently even if the sidecar reboots while the
# source session is quiet.
LATCH_FILE = os.getenv("LATCH_FILE", "/tmp/midvox-latched-presence.json")
# How often the latched presence is re-announced (also advances the Spotify
# progress bar so the track keeps looking live).
REFRESH_SECS = float(os.getenv("PRESENCE_REFRESH_SECS", "60"))
# Detail logging: every gateway event, session inventory, and OP3 payload.
VERBOSE = os.getenv("PRESENCE_VERBOSE", "1") == "1"
LATCHED: list = []
LATCHED_AT = 0.0


def load_latched() -> bool:
    """Restore latched presence saved by a previous run."""
    global LATCHED, LATCHED_AT
    try:
        with open(LATCH_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        activities = data.get("activities") or []
        if isinstance(activities, list) and activities:
            LATCHED = [a for a in activities if isinstance(a, dict)]
            LATCHED_AT = float(data.get("latched_at") or 0.0) or time.time()
            return True
    except (OSError, ValueError):
        pass
    return False


def save_latched() -> None:
    with contextlib.suppress(OSError):
        with open(LATCH_FILE, "w", encoding="utf-8") as handle:
            json.dump({"activities": LATCHED, "latched_at": LATCHED_AT}, handle)


def has_spotify(activities) -> bool:
    """True when the list carries a real Spotify activity."""
    for activity in activities or []:
        if not isinstance(activity, dict):
            continue
        try:
            activity_type = int(activity.get("type"))
        except (TypeError, ValueError):
            continue
        if activity_type == 2 and str(activity.get("name") or "").lower() == "spotify":
            return True
    return False


def should_adopt(mirrored) -> bool:
    """Adopt only sets that add or change details — never a quiet source.

    A non-empty list that merely lost the latched Spotify (source went
    quiet, status toggled, partial list) must not wipe the latch.
    """
    if not mirrored:
        return False
    if activities_signature(mirrored) == activities_signature(LATCHED):
        return False
    if has_spotify(LATCHED) and not has_spotify(mirrored):
        return False
    return True


def shifted_latched() -> list:
    """Return latched activities refreshed to look live right now.

    The track keeps its real details (title, artist, album art); the
    progress bar is looped forward and created_at renewed so Discord never
    treats the activity as stale/expired and drops it from the status.
    """
    now_ms = int(time.time() * 1000)
    elapsed_ms = max(0, int(time.time() - LATCHED_AT) * 1000)
    outgoing = []
    for activity in LATCHED:
        activity = dict(activity)
        activity["created_at"] = now_ms
        stamps = activity.get("timestamps") or {}
        try:
            start = int(stamps.get("start") or 0)
            end = int(stamps.get("end") or 0)
        except (TypeError, ValueError):
            start = end = 0
        if start > 0 and end > start:
            duration = end - start
            position = elapsed_ms % duration
            activity["timestamps"] = {
                **stamps,
                "start": now_ms - position,
                "end": now_ms - position + duration,
            }
        outgoing.append(activity)
    return outgoing


def inventory_lines(data) -> list:
    """One log line per session: device, status, activity types/names."""
    from presence_mirror import extract_session_list

    lines = []
    for session in extract_session_list(data):
        sid = str(session.get("session_id") or "?")[:8]
        client = (session.get("client_info") or {}).get("client", "?")
        status = session.get("status", "?")
        acts = []
        for activity in session.get("activities") or []:
            if isinstance(activity, dict):
                acts.append(
                    f"{activity.get('type')}:{activity.get('name')}"
                )
        lines.append(
            f"session {sid}… client={client} status={status} "
            f"activities=[{','.join(acts) or 'none'}]"
        )
    return lines


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
        # Fail fast with no waiting: loop() already waits once at startup for
        # the gateway session. Waiting 30s here stalled every bump interval
        # and made /bump look dead when the desktop-only path never set
        # SESSION_ID.
        print("[bump] gateway session not ready; skipping (no wait)", flush=True)
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


async def heartbeat(ws, interval, sequence, last_ack):
    """Heartbeat immediately, then on schedule, watching for ACKs."""
    await asyncio.sleep(random.uniform(0, min(2.0, interval)))
    while not ws.closed:
        await ws.send_json({"op": 1, "d": sequence[0]})
        sent_at = time.monotonic()
        await asyncio.sleep(interval)
        if last_ack[0] < sent_at:
            raise RuntimeError("Discord gateway did not acknowledge heartbeat")


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


async def authenticate_desktop(session, target):
    """Write the user token into the official app and reload it once.

    The token must be stored on the app's own origin (discordapp.com); writing
    it anywhere else is never read back. A full page reload is required so the
    app boot picks the token up — an in-app navigation does not re-read it.
    Reloading replaces the CDP target, so a dropped DevTools connection at
    that point is expected and not an error.
    """
    token_literal = json.dumps(TOKEN)
    async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
        handoff = await cdp_call(
            ws,
            1,
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => {"
                    f"const token = {token_literal};"
                    "const expected = JSON.stringify(token);"
                    "const readToken = () => {"
                    "const frame = document.createElement('iframe');"
                    "frame.style.display = 'none';"
                    "document.body.appendChild(frame);"
                    "const value = frame.contentWindow.localStorage."
                    "getItem('token');"
                    "frame.remove();"
                    "return value;"
                    "};"
                    "if (readToken() === expected) return 'ready';"
                    "const frame = document.createElement('iframe');"
                    "frame.style.display = 'none';"
                    "document.body.appendChild(frame);"
                    "frame.contentWindow.localStorage.setItem("
                    "'token', expected);"
                    "frame.remove();"
                    "return readToken() === expected ? 'stored' : 'failed';"
                    "})()"
                ),
                "returnByValue": True,
            },
        )
        result = (handoff.get("result", {}) or {}).get("value")
        if result == "ready":
            return True
        if result != "stored":
            raise RuntimeError("Discord token was not stored by desktop")

    try:
        async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
            await cdp_call(ws, 2, "Page.reload", {})
    except (aiohttp.ClientError, RuntimeError):
        pass
    return False


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
        # An unauthenticated client also logs Gateway READY, so that alone
        # proves nothing. Only a numeric active-user login marks the desktop
        # as the online base device.
        marker = "active user changed (now: "
        if marker in text:
            user_id = text.split(marker, 1)[1].split(",", 1)[0].strip()
            if user_id.isdigit():
                with contextlib.suppress(OSError):
                    with open(
                        USER_DESKTOP_READY_FILE,
                        "w",
                        encoding="utf-8",
                    ) as ready_file:
                        ready_file.write(user_id)
                print(
                    "[user-desktop] Discord account "
                    f"{user_id} online on official desktop",
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


async def discord_desktop_client():
    """Keep Discord's official desktop client open on a virtual display."""
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
                        token_reused = await authenticate_desktop(session, target)
                    except asyncio.CancelledError:
                        raise
                    except (aiohttp.ClientError, RuntimeError, ValueError) as error:
                        print(
                            "[discord-desktop] authentication handoff failed: "
                            f"{error}",
                            flush=True,
                        )
                        token_reused = False
                    if token_reused:
                        print(
                            "[discord-desktop] existing desktop authentication "
                            "reused; Gateway left uninterrupted",
                            flush=True,
                        )
                    else:
                        print(
                            "[discord-desktop] token stored; reloaded official "
                            "desktop to complete login",
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
    """Hold one Discord gateway session open forever, like a normal client.

    Logs in, stays online, resumes across drops. Presence rule is a latch:
    whenever another session of the account shows real activities (Spotify
    with full details, custom status, ...), those exact details are adopted
    and then re-shown permanently — even after the source session goes
    quiet. Nothing is ever cleared. The session also supplies SESSION_ID
    for normal /bump interactions.
    """
    global SESSION_ID
    global RESUME_GATEWAY_URL, RESUME_SESSION_ID, RESUME_SEQ
    global RECONNECT_DELAY
    global LATCHED, LATCHED_AT

    identify_payload = {
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

    load_latched()

    while True:
        resume_attempt = bool(RESUME_SESSION_ID)
        url = RESUME_GATEWAY_URL or GATEWAY
        reconnect_requested = False
        invalid_resumable = None
        close_code = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=None) as ws:
                    try:
                        hello = await asyncio.wait_for(ws.receive_json(), timeout=20)
                    except TimeoutError:
                        raise RuntimeError("Discord gateway did not send HELLO")
                    if hello.get("op") != 10:
                        raise RuntimeError("Discord gateway did not send HELLO")

                    interval = hello["d"]["heartbeat_interval"] / 1000
                    sequence = [RESUME_SEQ]
                    last_ack = [time.monotonic()]
                    heartbeat_task = asyncio.create_task(
                        heartbeat(ws, interval, sequence, last_ack)
                    )
                    try:
                        if resume_attempt:
                            await ws.send_json(
                                {
                                    "op": 6,
                                    "d": {
                                        "token": TOKEN,
                                        "session_id": RESUME_SESSION_ID,
                                        "seq": RESUME_SEQ,
                                    },
                                }
                            )
                            print(
                                "[user-presence] resuming gateway session",
                                flush=True,
                            )
                        else:
                            await ws.send_json(identify_payload)
                            print(
                                "[user-presence] Gateway identified; "
                                "waiting for READY",
                                flush=True,
                            )

                        async def show(activities, source):
                            # Single OP3 writer: online with the given
                            # activities. (Some routing paths ignore Identify
                            # presence until an OP3 arrives.)
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
                            summary = summarize_activities(activities)
                            print(
                                "[user-presence] ONLINE as Linux Desktop with "
                                f"{len(activities)} activities "
                                f"({summary or 'none'}) from {source}",
                                flush=True,
                            )
                            if VERBOSE:
                                print(
                                    "[user-presence] OP3 payload: "
                                    f"{json.dumps(activities, separators=(',', ':'))[:2000]}",
                                    flush=True,
                                )

                        async def adopt_latched(mirrored, source):
                            global LATCHED, LATCHED_AT
                            LATCHED = mirrored
                            LATCHED_AT = time.time()
                            save_latched()
                            await show(shifted_latched(), f"{source} (adopted)")

                        async def refresh_loop():
                            # Keep the latched track alive with a moving
                            # progress bar; silent to avoid log spam.
                            while not ws.closed:
                                await asyncio.sleep(REFRESH_SECS)
                                if LATCHED and SESSION_ID and not ws.closed:
                                    with contextlib.suppress(Exception):
                                        await ws.send_json(
                                            {
                                                "op": 3,
                                                "d": {
                                                    "status": "online",
                                                    "since": 0,
                                                    "activities": shifted_latched(),
                                                    "afk": False,
                                                },
                                            }
                                        )

                        def mark_ready():
                            with contextlib.suppress(OSError):
                                with open(
                                    USER_PRESENCE_READY_FILE,
                                    "w",
                                    encoding="utf-8",
                                ) as ready_file:
                                    ready_file.write(SESSION_ID)
                            SESSION_READY.set()

                        receive_timeout = max(30.0, interval * 1.5)
                        refresh_task = asyncio.create_task(refresh_loop())
                        while True:
                            try:
                                message = await asyncio.wait_for(
                                    ws.receive(), timeout=receive_timeout
                                )
                            except TimeoutError:
                                raise RuntimeError("Discord gateway receive timeout")
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                if payload.get("s") is not None:
                                    sequence[0] = payload["s"]
                                    RESUME_SEQ = payload["s"]
                                op = payload.get("op")
                                if op == 11:
                                    last_ack[0] = time.monotonic()
                                elif op == 0 and payload.get("t") == "READY":
                                    data = payload.get("d", {})
                                    SESSION_ID = str(data.get("session_id") or "")
                                    if VERBOSE:
                                        print(
                                            "[user-presence] READY inventory:",
                                            flush=True,
                                        )
                                        for line in inventory_lines(data):
                                            print(
                                                f"[user-presence]   {line}",
                                                flush=True,
                                            )
                                    if SESSION_ID:
                                        RESUME_GATEWAY_URL = str(
                                            data.get("resume_gateway_url") or GATEWAY
                                        )
                                        RESUME_SESSION_ID = SESSION_ID
                                        mirrored = mirrorable_session_activities(
                                            data, SESSION_ID
                                        )
                                        if should_adopt(mirrored):
                                            await adopt_latched(mirrored, "READY")
                                        elif LATCHED:
                                            await show(
                                                shifted_latched(),
                                                "READY (latched)",
                                            )
                                        else:
                                            await show([], "READY")
                                        mark_ready()
                                        RECONNECT_DELAY = INITIAL_BACKOFF
                                elif op == 0 and payload.get("t") == "RESUMED":
                                    SESSION_ID = RESUME_SESSION_ID
                                    if SESSION_ID:
                                        mark_ready()
                                        if LATCHED:
                                            await show(
                                                shifted_latched(), "RESUMED"
                                            )
                                        else:
                                            print(
                                                "[user-presence] resumed gateway "
                                                "session; still ONLINE",
                                                flush=True,
                                            )
                                        RECONNECT_DELAY = INITIAL_BACKOFF
                                elif (
                                    op == 0
                                    and payload.get("t") == "SESSIONS_REPLACE"
                                ):
                                    # Adopt real details when they appear;
                                    # never adopt a quiet source over latched
                                    # Spotify.
                                    if VERBOSE:
                                        print(
                                            "[user-presence] SESSIONS_REPLACE inventory:",
                                            flush=True,
                                        )
                                        for line in inventory_lines(
                                            payload.get("d", [])
                                        ):
                                            print(
                                                f"[user-presence]   {line}",
                                                flush=True,
                                            )
                                    mirrored = mirrorable_session_activities(
                                        payload.get("d", []), SESSION_ID
                                    )
                                    if should_adopt(mirrored):
                                        await adopt_latched(
                                            mirrored, "SESSIONS_REPLACE"
                                        )
                                    elif VERBOSE and mirrored:
                                        print(
                                            "[user-presence] source went quiet; "
                                            "keeping latched Spotify",
                                            flush=True,
                                        )
                                if op == 1:
                                    await ws.send_json({"op": 1, "d": sequence[0]})
                                elif op in (7, 9):
                                    if op == 7:
                                        reconnect_requested = True
                                    else:
                                        invalid_resumable = bool(payload.get("d"))
                                    print(
                                        "[user-presence] gateway asked to "
                                        f"{'reconnect' if op == 7 else 're-identify '
                                        f"(resumable={bool(payload.get('d'))})"}",
                                        flush=True,
                                    )
                                    break
                            elif message.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                close_code = ws.close_code
                                break
                    finally:
                        SESSION_ID = ""
                        SESSION_READY.clear()
                        with contextlib.suppress(OSError):
                            os.remove(USER_PRESENCE_READY_FILE)
                        heartbeat_task.cancel()
                        refresh_task.cancel()
                        await asyncio.gather(
                            heartbeat_task, refresh_task, return_exceptions=True
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[user-presence] error: {e}", flush=True)

        resumable = should_resume(
            invalid_resumable, close_code, bool(RESUME_SESSION_ID)
        )
        if not resumable:
            RESUME_GATEWAY_URL = GATEWAY
            RESUME_SESSION_ID = ""
            RESUME_SEQ = None

        delay = RECONNECT_DELAY
        RECONNECT_DELAY = next_backoff(RECONNECT_DELAY)
        action = "resuming" if resumable else "reconnecting"
        print(
            f"[user-presence] {action} in {delay:g}s "
            f"(close_code={close_code} invalid_resumable={invalid_resumable})",
            flush=True,
        )
        if close_code in AUTH_FAILED_CLOSE_CODES:
            print(
                "[user-presence] Discord rejected USER_TOKEN (4004 "
                "Authentication failed): wrong token, password changed, or "
                "account locked/flagged. Fix the token or unlock the account; "
                "retrying with backoff until then.",
                flush=True,
            )
        await asyncio.sleep(delay)


async def loop():
    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEyMC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTIwLjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjIyMzgxNiwiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0=",
    }
    print(f"[bump] start channel={CHANNEL_ID} every {INTERVAL}s", flush=True)
    # Wait once at startup for the gateway session so the first bump fires
    # immediately after READY instead of stalling 30s inside every send_bump.
    try:
        await asyncio.wait_for(SESSION_READY.wait(), timeout=60)
    except TimeoutError:
        print(
            "[bump] gateway not ready after 60s; will retry each interval",
            flush=True,
        )
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
        # Gateway-only presence: one lightweight connection stays online
        # permanently with resume + backoff and supplies SESSION_ID for
        # normal /bump interactions. Presence is a latch: real details from
        # the account's other sessions are adopted once, then re-shown
        # forever (survives quiet sources, reconnects, restarts). No
        # Electron desktop: it was slow to boot, restarted in loops, and any
        # second publishing session fought the display and dropped songs.
        # (discord_desktop_client remains in this file but is not started.)
        # Fail fast with a clear message when Discord rejects the token over
        # REST, instead of looping on gateway 4004s.
        async with aiohttp.ClientSession() as validation_session:
            try:
                await validate_user_token(validation_session)
            except RuntimeError as error:
                print(
                    f"[presence] FATAL: {error} — Discord rejected USER_TOKEN. "
                    "Wrong token, password changed, or account locked/flagged. "
                    "Fix the token or unlock the account and redeploy.",
                    flush=True,
                )
                raise
        print("[presence] USER_TOKEN accepted by Discord", flush=True)
        presence_task = asyncio.create_task(
            supervise("user-presence", connect_presence)
        )
        try:
            await asyncio.wait_for(SESSION_READY.wait(), timeout=60)
        except TimeoutError:
            presence_task.cancel()
            await asyncio.gather(presence_task, return_exceptions=True)
            raise RuntimeError("User-account gateway did not become ready")
        # start.sh waits on USER_DESKTOP_READY_FILE: bridge gateway readiness
        # so remaining services start at once.
        if not os.path.isfile(USER_DESKTOP_READY_FILE):
            with contextlib.suppress(OSError):
                with open(
                    USER_DESKTOP_READY_FILE,
                    "w",
                    encoding="utf-8",
                ) as ready_file:
                    ready_file.write(SESSION_ID or "gateway")
        print(
            "[user-presence] ONLINE permanent "
            f"(session {SESSION_ID[:8]}…); starting /bump and remaining services",
            flush=True,
        )

        tasks = [presence_task]
        if CHANNEL_ID:
            tasks.append(supervise("bump", loop))
        await asyncio.gather(*tasks)

    asyncio.run(main())
