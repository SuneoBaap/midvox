# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/codexdev                      ║
# ║   youtube  ──  https://youtube.com/@CodeXDevs                   ║
# ║   github   ──  https://github.com/RayExo                        ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

"""
Media Downloader — when an Instagram link or a YouTube Short is posted in
a configured channel, download the media and repost it to Discord so it
plays inline. Instagram embeds don't render in Discord, hence the bot.

Storage mirrors the AntiSpamPlus pattern: SQLite is always written (a
crash/restart-safe mirror), MongoDB is the durable store when reachable.
"""

import discord
from discord.ext import commands
import aiosqlite
import asyncio
import json
import os
import re
import time
import tempfile
import urllib.request
import urllib.error
from collections import defaultdict

INSTA_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|dl\.)?(?:instagram\.com|instagr\.am)/"
    r"(?:reel|reels|p|tv|stories|share)/[\w\-]+",
    re.IGNORECASE,
)

YT_SHORTS_URL_RE = re.compile(
    r"(?:https?://)?(?:(?:www\.|m\.)?youtube\.com/shorts/|(?:www\.)?youtu\.be/)([\w\-]{6,20})",
    re.IGNORECASE,
)

CONFIG_DEFAULTS = {
    "enabled": False,
    "delete_original": True,
}

# Discord's upload limit varies by plan/server. Keep a safety margin below the
# common 10 MB limit unless the deployment explicitly raises it.
UPLOAD_LIMIT_BYTES = int(os.getenv("DISCORD_UPLOAD_LIMIT", "9500000"))


class InstaDownloader(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._channel_cooldown = defaultdict(float)
        self._download_lock = asyncio.Lock()
        self._active_status_id = None

    @property
    def mongo(self):
        return getattr(self.bot, "mongo", None)

    async def _ensure_mongo(self):
        """Lazy-connect Mongo on demand so reads never fall back to an
        empty SQLite mirror right after a redeploy."""
        if self.mongo:
            return True
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return False
        try:
            from utils.mongo import MongoManager
            mongo = MongoManager()
            await mongo.connect(mongo_uri, server_selection_timeout=5000)
            self.bot.mongo = mongo
            print("\033[32m◈ MongoDB: Connected (lazy, InstaDL)\033[0m")
            return True
        except Exception as e:
            print(f"\033[33m◈ MongoDB: lazy connect failed (InstaDL) — {e}\033[0m")
            return False

    # ── SQLite mirror ──────────────────────────────────────────────────

    def _sqlite_conn(self):
        os.makedirs("db", exist_ok=True)
        return aiosqlite.connect("db/instadl.db")

    async def _ensure_tables(self, db):
        tables = [
            """CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                delete_original INTEGER DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS channels (
                guild_id INTEGER, channel_id INTEGER, PRIMARY KEY (guild_id, channel_id)
            )""",
        ]
        for t in tables:
            await db.execute(t)
        await db.commit()

    async def _sqlite_get_config(self, guild_id):
        async with self._sqlite_conn() as db:
            await self._ensure_tables(db)
            cursor = await db.execute(
                "SELECT enabled, delete_original FROM config WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cursor.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO config (guild_id, delete_original) VALUES (?, 1)",
                    (guild_id,),
                )
                await db.commit()
                row = (0, 1)
            elif row[0] and not row[1]:
                # Older installs defaulted to keeping the link. Migrate an
                # enabled downloader to the current always-clean behavior.
                await db.execute(
                    "UPDATE config SET delete_original = 1 WHERE guild_id = ?",
                    (guild_id,),
                )
                await db.commit()
                row = (row[0], 1)
            cursor = await db.execute(
                "SELECT channel_id FROM channels WHERE guild_id = ?", (guild_id,)
            )
            channels = [r[0] for r in await cursor.fetchall()]
            return {
                "guild_id": guild_id,
                "enabled": bool(row[0]),
                "delete_original": bool(row[1]),
                "channels": [str(c) for c in channels],
            }

    # ── Mongo (durable) ────────────────────────────────────────────────

    def _default_doc(self, guild_id):
        return {
            "_id": str(guild_id),
            "guild_id": guild_id,
            **CONFIG_DEFAULTS,
            "channels": [],
        }

    async def _flush_to_mongo(self, guild_id, sqlite_cfg):
        """Push the SQLite mirror state into Mongo (lazy flush on read)."""
        if not self.mongo:
            return
        try:
            doc = self._default_doc(guild_id)
            doc.update(sqlite_cfg)
            doc["guild_id"] = int(guild_id)
            doc["_id"] = str(guild_id)
            doc.pop("_doc_id", None)
            await self.mongo.instadl_config.replace_one(
                {"_id": str(guild_id)}, doc, upsert=True
            )
        except Exception as e:
            print(f"[InstaDL] Mongo flush failed for {guild_id}: {e}")

    async def _mongo_get(self, guild_id):
        if not self.mongo:
            return None
        try:
            return await self.mongo.instadl_config.find_one({"_id": str(guild_id)})
        except Exception as e:
            print(f"[InstaDL] Mongo read failed: {e}")
            return None

    # ── Public API (used by bot/api routes) ────────────────────────────

    async def get_config(self, guild_id):
        await self._ensure_mongo()
        doc = await self._mongo_get(guild_id)
        if doc:
            if doc.get("enabled") and not doc.get("delete_original", False):
                try:
                    await self.mongo.instadl_config.update_one(
                        {"_id": str(guild_id)}, {"$set": {"delete_original": True}}
                    )
                    doc["delete_original"] = True
                except Exception as e:
                    print(f"[InstaDL] delete-original migration failed: {e}")
            return {
                "guild_id": guild_id,
                "enabled": bool(doc.get("enabled", False)),
                "delete_original": bool(doc.get("delete_original", False)),
                "channels": [str(c) for c in doc.get("channels", [])],
            }
        cfg = await self._sqlite_get_config(guild_id)
        # Lazy flush: if Mongo is reachable but the doc is missing, push
        # the mirror state so nothing saved during an outage is lost.
        if self.mongo and (cfg["enabled"] or cfg["channels"] or cfg["delete_original"]):
            await self._flush_to_mongo(guild_id, cfg)
        return cfg

    async def update_config(self, guild_id, data):
        async with self._sqlite_conn() as db:
            await self._ensure_tables(db)
            row = await (await db.execute(
                "SELECT enabled, delete_original FROM config WHERE guild_id = ?",
                (guild_id,),
            )).fetchone()
            enabled = row[0] if row else 0
            delete_original = row[1] if row else 0
            if "enabled" in data:
                enabled = 1 if data["enabled"] else 0
                if enabled and "delete_original" not in data:
                    delete_original = 1
            if "delete_original" in data:
                delete_original = 1 if data["delete_original"] else 0
            await db.execute(
                """INSERT OR REPLACE INTO config (guild_id, enabled, delete_original)
                   VALUES (?, ?, ?)""",
                (guild_id, enabled, delete_original),
            )
            await db.commit()

        await self._ensure_mongo()
        if self.mongo:
            doc = await self._mongo_get(guild_id)
            if doc:
                doc["enabled"] = bool(enabled)
                doc["delete_original"] = bool(delete_original)
                try:
                    await self.mongo.instadl_config.replace_one(
                        {"_id": str(guild_id)}, doc, upsert=True
                    )
                except Exception as e:
                    print(f"[InstaDL] Mongo update failed (mirror kept): {e}")
            else:
                await self._flush_to_mongo(guild_id, await self._sqlite_get_config(guild_id))
        return await self.get_config(guild_id)

    async def add_channel(self, guild_id, channel_id):
        try:
            async with self._sqlite_conn() as db:
                await self._ensure_tables(db)
                await db.execute(
                    "INSERT OR IGNORE INTO channels (guild_id, channel_id) VALUES (?, ?)",
                    (guild_id, channel_id),
                )
                await db.commit()
        except Exception as e:
            print(f"[InstaDL] SQLite mirror write failed: {e}")
        await self._ensure_mongo()
        if self.mongo:
            try:
                await self.mongo.instadl_config.update_one(
                    {"_id": str(guild_id)},
                    {"$addToSet": {"channels": str(channel_id)}},
                    upsert=True,
                )
            except Exception as e:
                print(f"[InstaDL] Mongo channel add failed (mirror kept): {e}")
        return await self.get_config(guild_id)

    async def remove_channel(self, guild_id, channel_id):
        try:
            async with self._sqlite_conn() as db:
                await self._ensure_tables(db)
                await db.execute(
                    "DELETE FROM channels WHERE guild_id = ? AND channel_id = ?",
                    (guild_id, channel_id),
                )
                await db.commit()
        except Exception as e:
            print(f"[InstaDL] SQLite mirror delete failed: {e}")
        await self._ensure_mongo()
        if self.mongo:
            try:
                await self.mongo.instadl_config.update_one(
                    {"_id": str(guild_id)},
                    {"$pull": {"channels": str(channel_id)}},
                )
            except Exception as e:
                print(f"[InstaDL] Mongo channel remove failed (mirror kept): {e}")
        return await self.get_config(guild_id)

    # ── Downloader ─────────────────────────────────────────────────────

    async def _auto_delete(self, msg, delay=60):
        """Delete a bot status message after `delay` seconds (media posts
        are never auto-deleted — only status/error messages use this)."""

        async def _delete_later():
            try:
                await asyncio.sleep(delay)
                await msg.delete()
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_delete_later())
        except Exception:
            pass

    async def _send_status(self, channel, text, reference=None, auto_delete=60):
        try:
            msg = await channel.send(text, reference=reference)
        except Exception:
            try:
                msg = await channel.send(text)
            except Exception:
                return None
        if auto_delete:
            await self._auto_delete(msg, auto_delete)
        return msg

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot or not message.guild:
                return
            if not isinstance(message.channel, discord.TextChannel):
                return

            config = await self.get_config(message.guild.id)
            if not config.get("enabled"):
                return
            if str(message.channel.id) not in config.get("channels", []):
                return

            content = message.content or ""
            insta_match = INSTA_URL_RE.search(content)
            yt_match = YT_SHORTS_URL_RE.search(content)
            if not insta_match and not yt_match:
                return

            if insta_match:
                url = insta_match.group(0)
                source = "instagram"
            else:
                url = yt_match.group(0)
                source = "youtube"

            if not url.startswith("http"):
                url = "https://" + url

            # Per-channel cooldown so a spam of links can't hammer the sites
            now = time.time()
            key = str(message.channel.id)
            if now - self._channel_cooldown.get(key, 0) < 8:
                return
            self._channel_cooldown[key] = now

            print(f"[InstaDL] downloading {source} url {url} for guild {message.guild.id}")
            await self._download_and_send(message, url, config, source)
        except Exception as e:
            print(f"[InstaDL] on_message error: {e}")

    @commands.Cog.listener(name="on_message")
    async def _cleanup_bot_messages(self, message):
        """Auto-delete the bot's own status/error messages in configured
        channels. Media posts (videos/images) are never deleted."""
        try:
            if message.author.id != self.bot.user.id:
                return
            if not message.guild or not isinstance(message.channel, discord.TextChannel):
                return
            config = await self.get_config(message.guild.id)
            if not config.get("enabled"):
                return
            if str(message.channel.id) not in config.get("channels", []):
                return
            if message.attachments or (message.embeds and not message.content):
                return
            if self._active_status_id == message.id:
                return

            await asyncio.sleep(20)

            async def _delete_later():
                try:
                    await message.delete()
                except Exception:
                    pass

            asyncio.get_running_loop().create_task(_delete_later())
        except Exception as e:
            print(f"[InstaDL] cleanup error: {e}")

    def _cobalt_download(self, url):
        """Download a YouTube Short through a public Cobalt instance.

        Cobalt performs the extraction/remuxing remotely. This bot deliberately
        does not pass YouTube cookies, invoke yt-dlp, or run local FFmpeg for
        Shorts. Railway starts the compatible Cobalt runtime locally and
        exposes it to the bot through ``COBALT_API_URL``.
        """
        base_url = os.getenv(
            "COBALT_API_URL", "http://127.0.0.1:9000"
        ).strip().rstrip("/")
        def _request(quality):
            body = json.dumps(
                {
                    "url": url,
                    "videoQuality": quality,
                    # H.264 is broadly playable in Discord. The quality is
                    # selected below after probing the returned file size.
                    "youtubeVideoCodec": "h264",
                    "youtubeVideoContainer": "mp4",
                    "youtubeBetterAudio": False,
                    "downloadMode": "auto",
                    "localProcessing": "disabled",
                }
            ).encode()
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "MidVox/1.0 (+https://github.com/suneo779/midvox)",
            }
            last_error = None
            for endpoint in (base_url, f"{base_url}/api/json"):
                try:
                    req = urllib.request.Request(
                        endpoint, data=body, method="POST", headers=headers
                    )
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        return json.loads(resp.read().decode("utf-8", "replace"))
                except urllib.error.HTTPError as exc:
                    last_error = exc
                    try:
                        raw_error = exc.read().decode("utf-8", "replace")
                        parsed_error = json.loads(raw_error)
                        error_obj = parsed_error.get("error", parsed_error)
                        error_code = (
                            error_obj.get("code")
                            if isinstance(error_obj, dict)
                            else error_obj
                        )
                        print(
                            f"[InstaDL] cobalt HTTP {exc.code}: "
                            f"{error_code or raw_error[:300]}"
                        )
                    except Exception:
                        print(f"[InstaDL] cobalt HTTP {exc.code}: {exc}")
                    if exc.code not in (404, 405):
                        return None
            if last_error:
                print(f"[InstaDL] cobalt request failed: {last_error}")
            return None

        def _probe_size(media_url):
            try:
                probe = urllib.request.Request(
                    media_url,
                    method="HEAD",
                    headers={
                        "User-Agent": "MidVox/1.0 (+https://github.com/suneo779/midvox)",
                    },
                )
                with urllib.request.urlopen(probe, timeout=15) as resp:
                    for header in ("Content-Length", "Estimated-Content-Length"):
                        value = resp.headers.get(header)
                        if value and str(value).isdigit():
                            return int(value)
            except Exception as exc:
                print(f"[InstaDL] cobalt size probe unavailable: {exc}")
            return None

        try:
            # Ask Cobalt for the best option first, but do not download it
            # until its tunnel/redirect reports a size within Discord's limit.
            for quality in ("max", "1080", "720", "480", "360", "240"):
                data = _request(quality)
                if not isinstance(data, dict):
                    # A request-level failure (for example YouTube blocking
                    # the instance) will not be fixed by trying resolutions.
                    return None
                status = data.get("status")
                media_url = data.get("url")
                if status not in ("redirect", "tunnel") or not media_url:
                    error = data.get("error")
                    if isinstance(error, dict):
                        error = error.get("code") or error
                    print(f"[InstaDL] cobalt error at {quality}: {error or status}")
                    return None

                expected_size = _probe_size(media_url)
                if expected_size and expected_size > UPLOAD_LIMIT_BYTES:
                    print(
                        f"[InstaDL] skipping cobalt {quality}: "
                        f"{expected_size} bytes exceeds Discord limit"
                    )
                    continue

                dreq = urllib.request.Request(
                    media_url,
                    headers={
                        "User-Agent": "MidVox/1.0 (+https://github.com/suneo779/midvox)",
                    },
                )
                with urllib.request.urlopen(dreq, timeout=120) as resp:
                    content_type = resp.headers.get_content_type()
                    suffix = ".mp4" if content_type == "video/mp4" else ".webm"
                    path = os.path.join(
                        tempfile.gettempdir(),
                        f"cobalt_{int(time.time() * 1000)}{suffix}",
                    )
                    size = 0
                    with open(path, "wb") as output:
                        while True:
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > UPLOAD_LIMIT_BYTES:
                                break
                            output.write(chunk)
                if size > UPLOAD_LIMIT_BYTES:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    print(
                        f"[InstaDL] skipping cobalt {quality}: "
                        f"actual size {size} exceeds Discord limit"
                    )
                    continue
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    print(
                        f"[InstaDL] cobalt download OK at {quality}: "
                        f"{os.path.getsize(path)} bytes"
                    )
                    return path
            return None
        except Exception as e:
            print(f"[InstaDL] cobalt download failed: {e}")
            return None

    async def _download_and_send(self, message, url, config, source="instagram"):
        """Show an animated status, download and repost the media, then remove
        the source link when configured."""
        status = await self._send_status(
            message.channel, "Downloading ⏳", reference=None, auto_delete=0
        )
        self._active_status_id = status.id if status else None
        if status:
            # Animate "Downloading . / .. / ..." until the download finishes.
            asyncio.get_running_loop().create_task(
                self._animate_loading(status)
            )

        try:
            await self._download_and_send_inner(message, url, config, source)
        finally:
            self._active_status_id = None
            if status:
                try:
                    await status.delete()
                except Exception:
                    pass
            # Remove the source link after processing, including failed
            # downloads. This keeps the configured downloader channel clean.
            if config.get("delete_original"):
                try:
                    await message.delete()
                except Exception as e:
                    print(
                        f"[InstaDL] could not delete source message "
                        f"{message.id}: {e}"
                    )

    async def _animate_loading(self, status, interval=0.6):
        """Spin 'Downloading' through . → .. → ... while a download runs."""
        dots = ["", ".", "..", "..."]
        i = 0
        try:
            while True:
                await status.edit(content=f"Downloading {dots[i]} ⏳")
                i = (i + 1) % len(dots)
                await asyncio.sleep(interval)
        except (discord.NotFound, discord.HTTPException):
            return
        except Exception:
            return

    async def _download_and_send_inner(self, message, url, config, source="instagram"):
        """Download the media (YouTube via Cobalt, Instagram via yt-dlp) and
        repost it inline. `_download_and_send` wraps this with
        an immediate link deletion + animated loading indicator."""
        loop = asyncio.get_running_loop()
        file_path = None

        if source == "youtube":
            file_path = await loop.run_in_executor(None, self._cobalt_download, url)
            if not file_path:
                await self._send_status(
                    message.channel,
                    "Cobalt could not download that Short right now. Try again shortly.",
                    reference=message,
                )
                return
        else:
            try:
                import yt_dlp
            except ImportError:
                await self._send_status(
                    message.channel,
                    "Media Downloader is missing the `yt-dlp` dependency.",
                    reference=message,
                )
                return

            tmp = os.path.join(tempfile.gettempdir(), "instadl_%(id)s.%(ext)s")
            opts = {
                # Keep Instagram downloads to a single file so this bot never
                # needs a local FFmpeg merge process.
                "format": "b[ext=mp4]/b",
                "format_sort": ["res", "fps", "vcodec:av01", "vcodec:vp9", "vcodec:h264"],
                "outtmpl": tmp,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "max_filesize": 25 * 1024 * 1024,
                "socket_timeout": 25,
                "retries": 2,
                "fragment_retries": 2,
                "geo_bypass": True,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                },
            }
            def _download():
                last_err = None
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        path = ydl.prepare_filename(info)
                        if path and os.path.exists(path):
                            return path
                except Exception as e:
                    last_err = e
                    print(f"[InstaDL] yt-dlp attempt failed for {url}: {e}")
                if last_err:
                    raise last_err
                return None

            try:
                file_path = await loop.run_in_executor(None, _download)
            except Exception as e:
                reason = str(e).strip()[:300]
                print(f"[InstaDL] download failed for {url}: {e}")
                # yt-dlp can't do image-only posts — fall back to Instagram's
                # /media endpoint which serves the post image directly.
                if source == "instagram":
                    try:
                        if await self._send_image_fallback(message, url):
                            return
                    except Exception as fb:
                        print(f"[InstaDL] image fallback failed for {url}: {fb}")
                if reason and "requested format is not available" in reason.lower():
                    await self._send_status(
                        message.channel,
                        "The platform did not provide a compatible video format. "
                        "Try again shortly.",
                        reference=message,
                    )
                elif reason:
                    await self._send_status(
                        message.channel,
                        f"Couldn't download that link: `{reason}`",
                        reference=message,
                    )
                else:
                    await self._send_status(
                        message.channel,
                        f"Couldn't download that link: `{type(e).__name__}`",
                        reference=message,
                    )
                return

            if not file_path or not os.path.exists(file_path):
                await self._send_status(
                    message.channel,
                    f"Couldn't download that link — the platform likely blocked it or it's not downloadable.\n{url}",
                    reference=message,
                )
                return

        try:
            size = os.path.getsize(file_path)
            if size > UPLOAD_LIMIT_BYTES:
                await self._send_status(
                    message.channel,
                    "That media is too large for this Discord server's upload limit.",
                    reference=message,
                )
                return

            ext = os.path.splitext(file_path)[1] or ".mp4"
            try:
                await message.channel.send(
                    file=discord.File(
                        file_path, filename=f"{source}_{int(time.time())}{ext}"
                    )
                )
            except discord.HTTPException as e:
                await self._send_status(
                    message.channel,
                    "Discord rejected the upload because the file is too large.",
                    reference=message,
                )
                print(f"[InstaDL] Discord upload failed: {e}")
                return

        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

    async def _send_image_fallback(self, message, url):
        """Image-only posts (no video) — fetch the post image via the
        /media endpoint and repost it. Returns True if an image was sent."""
        m = re.search(r"/(?:reel|reels|p|tv|stories|share)/([\w\-]+)", url)
        if not m:
            return False
        code = m.group(1)
        media_url = f"https://www.instagram.com/p/{code}/media/?size=l"

        def _fetch():
            req = urllib.request.Request(media_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if not ctype.startswith("image/") or not data:
                    return None
                return data

        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _fetch)
        if not data:
            return False
        if len(data) > 25 * 1024 * 1024:
            return False

        path = os.path.join(tempfile.gettempdir(), f"instadl_{code}.jpg")
        with open(path, "wb") as f:
            f.write(data)
        try:
            await message.channel.send(
                file=discord.File(path, filename=f"instagram_{code}.jpg")
            )
            return True
        finally:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


def setup(bot):
    bot.add_cog(InstaDownloader(bot))
