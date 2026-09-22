import discord
from discord.ext import commands
import aiosqlite
import asyncio
import os
import time
from collections import defaultdict, deque
from utils.Tools import *
from utils.mongo import MongoManager, has_valid_mongo_uri


CONFIG_DEFAULTS = {
    "delete_messages": False,
    "delete_delay": 8,
    "re_limit": 5,
    "re_window": 30,
    "re_cooldown": 20,
    "re_delay": 0.35,
    "timeout_duration": 1,
}


def _doc_to_config(doc):
    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        "guild_id": int(doc["_id"]),
        "delete_messages": bool(doc.get("delete_messages", False)),
        "delete_delay": _int(doc.get("delete_delay", 8), 8),
        "re_limit": _int(doc.get("re_limit", 5), 5),
        "re_window": _int(doc.get("re_window", 30), 30),
        "re_cooldown": _int(doc.get("re_cooldown", 20), 20),
        "re_delay": float(doc.get("re_delay", 0.35) or 0.35),
        "timeout_duration": _int(doc.get("timeout_duration", 1), 1),
        "target_users": [str(u) for u in doc.get("target_users", [])],
        "blocked_commands": [str(c).lower() for c in doc.get("blocked_commands", [])],
        "excluded_channels": [str(c) for c in doc.get("excluded_channels", [])],
        "target_channels": [str(c) for c in doc.get("target_channels", [])],
        "_doc_id": str(doc["_id"]),
        "_doc_id_type": type(doc["_id"]).__name__,
    }


class AntiSpamPlus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_data = defaultdict(deque)
        self.message_reactions = defaultdict(lambda: defaultdict(int))
        self.cooldown = {}
        bot.loop.create_task(self._seed_blocked_commands())
        bot.loop.create_task(self._mongo_watch())

    @property
    def mongo(self):
        return getattr(self.bot, "mongo", None)

    async def _ensure_mongo(self):
        """Lazy-connect Mongo on demand so reads never fall back to an
        empty SQLite mirror right after a redeploy."""
        if self.mongo:
            return True
        mongo_uri = os.getenv("MONGO_URI")
        if not has_valid_mongo_uri(mongo_uri):
            return False
        try:
            mongo = MongoManager()
            await mongo.connect(mongo_uri, server_selection_timeout=5000)
            self.bot.mongo = mongo
            print("\033[32m◈ MongoDB: Connected (lazy)\033[0m")
            return True
        except Exception as e:
            print(f"\033[33m◈ MongoDB: lazy connect failed — {e}\033[0m")
            return False

    def _default_blocked_commands(self):
        prefixes = ["+", ";", ",", "!", "f", "=", ">", "$", "&"]
        commands = ["loop", "pause", "play", "skip", "stop", "vol", "volume"]
        return [f"{prefix}{cmd}" for cmd in commands for prefix in prefixes]

    async def _seed_blocked_commands_for(self, guild_id):
        seeded = self._default_blocked_commands()
        async with self._sqlite_conn() as db:
            await self._ensure_sqlite_tables(db)
            for cmd in seeded:
                try:
                    await db.execute(
                        "INSERT OR IGNORE INTO blocked_commands (guild_id, command) VALUES (?, ?)",
                        (guild_id, cmd),
                    )
                except Exception:
                    pass
            await db.commit()

        if self.mongo:
            doc = await self._find_doc(guild_id)
            if not doc:
                await self.mongo.antispamplus_config.insert_one(self._default_doc(guild_id))
                print(f"[AntiSpamPlus] seed: created doc for guild {guild_id}")
            else:
                await self.mongo.antispamplus_config.update_one(
                    {"_id": str(guild_id)},
                    {
                        "$addToSet": {"blocked_commands": {"$each": seeded}},
                        "$set": {"seeded_blocked_commands": True},
                    },
                )
                print(f"[AntiSpamPlus] seed: updated existing doc for guild {guild_id}")

    async def _seed_blocked_commands(self):
        await self.bot.wait_until_ready()
        guild_ids = [g.id for g in self.bot.guilds]
        print(f"  Seeding blocked commands for {len(guild_ids)} guild(s): {guild_ids}")
        for gid in guild_ids:
            try:
                await self._seed_blocked_commands_for(gid)
            except Exception as e:
                print(f"[AntiSpamPlus] Seed failed for guild {gid}: {e}")
        print(f"  Seeded {len(self._default_blocked_commands())} blocked commands for {len(guild_ids)} guild(s)")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        try:
            await self._seed_blocked_commands_for(guild.id)
            print(f"[AntiSpamPlus] Seeded blocked commands for new guild {guild.id}")
        except Exception as e:
            print(f"[AntiSpamPlus] Seed on join failed for guild {guild.id}: {e}")

    # ── MongoDB helpers (single document per guild) ──────────────────────

    def _default_doc(self, guild_id):
        return {
            "_id": str(guild_id),
            "guild_id": guild_id,
            **CONFIG_DEFAULTS,
            "target_users": [],
            "blocked_commands": self._default_blocked_commands(),
            "excluded_channels": [],
            "target_channels": [],
            "seeded_blocked_commands": True,
        }

    async def _find_doc(self, guild_id):
        key = str(guild_id)
        doc = await self.mongo.antispamplus_config.find_one({"_id": key})
        if doc:
            return doc
        doc = await self.mongo.antispamplus_config.find_one({"_id": guild_id})
        if doc:
            try:
                await self.mongo.antispamplus_config.insert_one({**doc, "_id": key})
            except Exception:
                pass
            await self.mongo.antispamplus_config.delete_one({"_id": doc["_id"]})
            print(f"[AntiSpamPlus] migrated doc _id {doc['_id']!r} -> {key!r}")
            return await self.mongo.antispamplus_config.find_one({"_id": key})
        return None

    async def _get_doc(self, guild_id):
        doc = await self._find_doc(guild_id)
        if doc:
            if not doc.get("seeded_blocked_commands"):
                await self.mongo.antispamplus_config.update_one(
                    {"_id": str(guild_id)},
                    {
                        "$addToSet": {
                            "blocked_commands": {"$each": self._default_blocked_commands()}
                        },
                        "$set": {"seeded_blocked_commands": True},
                    },
                )
                doc = await self.mongo.antispamplus_config.find_one(
                    {"_id": str(guild_id)}
                )
            return doc
        default = self._default_doc(guild_id)
        await self.mongo.antispamplus_config.update_one(
            {"_id": str(guild_id)},
            {"$setOnInsert": default},
            upsert=True,
        )
        return default

    async def _set_fields(self, guild_id, data):
        set_on_insert = self._default_doc(guild_id)
        update = {"$set": {}, "$setOnInsert": set_on_insert}
        for k in CONFIG_DEFAULTS:
            if k in data:
                update["$set"][k] = data[k]
        if update["$set"]:
            update["$set"]["guild_id"] = guild_id
            # Mongo rejects a path used in both $set and $setOnInsert
            for k in list(update["$set"]):
                set_on_insert.pop(k, None)
            await self.mongo.antispamplus_config.update_one(
                {"_id": str(guild_id)}, update, upsert=True
            )

    async def _push_array(self, guild_id, field, value):
        print(f"[AntiSpamPlus _push_array] guild={guild_id} field={field} value={value} (type={type(value).__name__})")
        set_on_insert = self._default_doc(guild_id)
        # Mongo rejects a path used in both $addToSet and $setOnInsert
        set_on_insert.pop(field, None)
        await self.mongo.antispamplus_config.update_one(
            {"_id": str(guild_id)},
            {
                "$addToSet": {field: value},
                "$setOnInsert": set_on_insert,
            },
            upsert=True,
        )
        after = await self.mongo.antispamplus_config.find_one({"_id": str(guild_id)})
        print(f"[AntiSpamPlus _push_array] guild={guild_id} after {field}={after.get(field, 'MISSING')}")

    async def _pull_array(self, guild_id, field, value):
        await self.mongo.antispamplus_config.update_one(
            {"_id": str(guild_id)}, {"$pull": {field: value}}
        )

    # ── SQLite helpers (fallback) ────────────────────────────────────────

    def _sqlite_conn(self):
        os.makedirs("db", exist_ok=True)
        return aiosqlite.connect("db/antispamplus.db")

    async def _ensure_sqlite_tables(self, db):
        tables = [
            """CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY, delete_messages INTEGER DEFAULT 0,
                delete_delay INTEGER DEFAULT 8, re_limit INTEGER DEFAULT 5,
                re_window INTEGER DEFAULT 30, re_cooldown INTEGER DEFAULT 20,
                re_delay REAL DEFAULT 0.35, timeout_duration INTEGER DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS target_users (
                guild_id INTEGER, user_id INTEGER, PRIMARY KEY (guild_id, user_id)
            )""",
            """CREATE TABLE IF NOT EXISTS blocked_commands (
                guild_id INTEGER, command TEXT, PRIMARY KEY (guild_id, command)
            )""",
            """CREATE TABLE IF NOT EXISTS excluded_channels (
                guild_id INTEGER, channel_id INTEGER, PRIMARY KEY (guild_id, channel_id)
            )""",
            """CREATE TABLE IF NOT EXISTS target_channels (
                guild_id INTEGER, channel_id INTEGER, PRIMARY KEY (guild_id, channel_id)
            )""",
        ]
        for t in tables:
            await db.execute(t)
        await db.commit()

    # ── Mongo reconnection + SQLite mirror flush ─────────────────────────

    async def _mongo_watch(self):
        """If Mongo wasn't reachable at startup, keep retrying in the
        background. On success, flush the SQLite mirror so no settings
        saved during the outage are lost."""
        await self.bot.wait_until_ready()
        mongo_uri = os.getenv("MONGO_URI")
        if not has_valid_mongo_uri(mongo_uri):
            print("\033[33m◈ MONGO_URI not set — SQLite-only mode\033[0m")
            return
        print("[AntiSpamPlus] Mongo watcher started (retries every 60s)")
        while True:
            try:
                if not self.mongo:
                    try:
                        mongo = MongoManager()
                        await mongo.connect(mongo_uri)
                        self.bot.mongo = mongo
                        print("\033[32m◈ MongoDB: Connected (background retry)\033[0m")
                        await self._flush_sqlite_to_mongo()
                    except Exception as e:
                        print(f"\033[33m◈ MongoDB: reconnect failed — {e}\033[0m")
            except Exception as e:
                print(f"[AntiSpamPlus] mongo watcher error: {e}")
            await asyncio.sleep(60)

    def _sqlite_row_meaningful(
        self, row, blocked_commands, target_users, excluded_channels, target_channels
    ):
        if row[1]:
            return True
        if any(
            row[i] != CONFIG_DEFAULTS[key]
            for i, key in [
                (2, "delete_delay"),
                (3, "re_limit"),
                (4, "re_window"),
                (5, "re_cooldown"),
                (6, "re_delay"),
                (7, "timeout_duration"),
            ]
        ):
            return True
        if target_users or excluded_channels or target_channels:
            return True
        if blocked_commands and set(
            b.lower() for b in blocked_commands
        ) != set(self._default_blocked_commands()):
            return True
        return False

    async def _flush_sqlite_to_mongo(self):
        """Push any user-modified SQLite state into MongoDB so data saved
        while Mongo was down survives. Default-only rows are skipped so a
        real Mongo doc is never clobbered by an empty mirror row."""
        if not self.mongo:
            return
        try:
            async with self._sqlite_conn() as db:
                await self._ensure_sqlite_tables(db)
                cursor = await db.execute("SELECT * FROM config")
                rows = await cursor.fetchall()
            flushed = 0
            for row in rows:
                gid = row[0]
                async with self._sqlite_conn() as db:
                    lists = {}
                    for table, key in [
                        ("target_users", "user_id"),
                        ("blocked_commands", "command"),
                        ("excluded_channels", "channel_id"),
                        ("target_channels", "channel_id"),
                    ]:
                        c = await db.execute(
                            f"SELECT {key} FROM {table} WHERE guild_id = ?", (gid,)
                        )
                        lists[table] = [r[0] for r in await c.fetchall()]
                if not self._sqlite_row_meaningful(
                    row,
                    lists["blocked_commands"],
                    lists["target_users"],
                    lists["excluded_channels"],
                    lists["target_channels"],
                ):
                    continue
                doc = {
                    "_id": str(gid),
                    "guild_id": gid,
                    "delete_messages": bool(row[1]),
                    "delete_delay": row[2],
                    "re_limit": row[3],
                    "re_window": row[4],
                    "re_cooldown": row[5],
                    "re_delay": row[6],
                    "timeout_duration": row[7],
                    "target_users": [str(u) for u in lists["target_users"]],
                    "blocked_commands": [
                        str(c).lower() for c in lists["blocked_commands"]
                    ],
                    "excluded_channels": [
                        str(c) for c in lists["excluded_channels"]
                    ],
                    "target_channels": [str(c) for c in lists["target_channels"]],
                    "seeded_blocked_commands": True,
                }
                await self.mongo.antispamplus_config.replace_one(
                    {"_id": str(gid)}, doc, upsert=True
                )
                flushed += 1
            print(f"[AntiSpamPlus] SQLite mirror -> MongoDB: flushed {flushed} guild(s)")
        except Exception as e:
            print(f"[AntiSpamPlus] flush to MongoDB failed: {e}")

    # ── Public API ───────────────────────────────────────────────────────

    async def _sqlite_get_config(self, guild_id):
        async with self._sqlite_conn() as db:
            await self._ensure_sqlite_tables(db)

            cursor = await db.execute(
                "SELECT * FROM config WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()

            if not row:
                await db.execute(
                    "INSERT INTO config (guild_id) VALUES (?)", (guild_id,)
                )
                await db.commit()
                row = (guild_id, 0, 8, 5, 30, 20, 0.35, 1)

            cursor = await db.execute(
                "SELECT user_id FROM target_users WHERE guild_id = ?", (guild_id,)
            )
            target_users = [r[0] for r in await cursor.fetchall()]
            cursor = await db.execute(
                "SELECT command FROM blocked_commands WHERE guild_id = ?", (guild_id,)
            )
            blocked_commands = [r[0] for r in await cursor.fetchall()]
            cursor = await db.execute(
                "SELECT channel_id FROM excluded_channels WHERE guild_id = ?",
                (guild_id,),
            )
            excluded_channels = [r[0] for r in await cursor.fetchall()]
            cursor = await db.execute(
                "SELECT channel_id FROM target_channels WHERE guild_id = ?",
                (guild_id,),
            )
            target_channels = [r[0] for r in await cursor.fetchall()]

            return {
                "guild_id": guild_id,
                "delete_messages": bool(row[1]),
                "delete_delay": row[2],
                "re_limit": row[3],
                "re_window": row[4],
                "re_cooldown": row[5],
                "re_delay": row[6],
                "timeout_duration": row[7],
                "target_users": [str(u) for u in target_users],
                "blocked_commands": blocked_commands,
                "excluded_channels": [str(c) for c in excluded_channels],
                "target_channels": [str(c) for c in target_channels],
            }

    async def get_config(self, guild_id):
        if await self._ensure_mongo():
            try:
                doc = await self._get_doc(guild_id)
                return _doc_to_config(doc)
            except Exception as e:
                print(f"[AntiSpamPlus] Mongo read failed, using SQLite mirror: {e}")
        return await self._sqlite_get_config(guild_id)

    async def update_config(self, guild_id, data):
        # SQLite mirror — always written so a Mongo outage can't lose data
        async with self._sqlite_conn() as db:
            await self._ensure_sqlite_tables(db)
            await db.execute(
                """INSERT OR REPLACE INTO config
                   (guild_id, delete_messages, delete_delay, re_limit,
                    re_window, re_cooldown, re_delay, timeout_duration)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    1 if data.get("delete_messages") else 0,
                    data.get("delete_delay", 8),
                    data.get("re_limit", 5),
                    data.get("re_window", 30),
                    data.get("re_cooldown", 20),
                    data.get("re_delay", 0.35),
                    data.get("timeout_duration", 1),
                ),
            )
            await db.commit()

        if await self._ensure_mongo():
            try:
                await self._set_fields(guild_id, data)
                return _doc_to_config(await self._get_doc(guild_id))
            except Exception as e:
                print(f"[AntiSpamPlus] Mongo update failed (SQLite mirror kept): {e}")
        return await self._sqlite_get_config(guild_id)

    async def _mirror_into(self, table, columns, values):
        """Write one row into the SQLite mirror (best-effort, never throws)."""
        try:
            async with self._sqlite_conn() as db:
                await self._ensure_sqlite_tables(db)
                await db.execute(
                    f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({', '.join(['?'] * len(values))})",
                    tuple(values),
                )
                await db.commit()
        except Exception as e:
            print(f"[AntiSpamPlus] SQLite mirror write failed: {e}")

    async def _mirror_out(self, table, column, *values):
        """Delete a row from the SQLite mirror (best-effort, never throws)."""
        try:
            async with self._sqlite_conn() as db:
                await self._ensure_sqlite_tables(db)
                await db.execute(
                    f"DELETE FROM {table} WHERE guild_id = ? AND {column} = ?",
                    tuple(values),
                )
                await db.commit()
        except Exception as e:
            print(f"[AntiSpamPlus] SQLite mirror delete failed: {e}")

    async def _mongo_write(self, coro, label):
        """Run a Mongo write; on failure keep the SQLite mirror and log."""
        if not self.mongo:
            return
        try:
            await coro
        except Exception as e:
            print(f"[AntiSpamPlus] Mongo write failed ({label}); SQLite mirror kept: {e}")

    async def add_target_user(self, guild_id, user_id):
        await self._mirror_into("target_users", "guild_id, user_id", (guild_id, user_id))
        if self.mongo:
            await self._mongo_write(
                self._push_array(guild_id, "target_users", user_id), "target_users"
            )

    async def remove_target_user(self, guild_id, user_id):
        await self._mirror_out("target_users", "user_id", guild_id, user_id)
        if self.mongo:
            await self._mongo_write(
                self._pull_array(guild_id, "target_users", user_id), "target_users"
            )

    async def add_blocked_command(self, guild_id, command):
        await self._mirror_into(
            "blocked_commands", "guild_id, command", (guild_id, command.lower())
        )
        if self.mongo:
            await self._mongo_write(
                self._push_array(guild_id, "blocked_commands", command.lower()),
                "blocked_commands",
            )

    async def remove_blocked_command(self, guild_id, command):
        await self._mirror_out(
            "blocked_commands", "command", guild_id, command.lower()
        )
        if self.mongo:
            await self._mongo_write(
                self._pull_array(guild_id, "blocked_commands", command.lower()),
                "blocked_commands",
            )

    async def add_excluded_channel(self, guild_id, channel_id):
        await self._mirror_into(
            "excluded_channels", "guild_id, channel_id", (guild_id, channel_id)
        )
        if self.mongo:
            await self._mongo_write(
                self._push_array(guild_id, "excluded_channels", channel_id),
                "excluded_channels",
            )

    async def remove_excluded_channel(self, guild_id, channel_id):
        await self._mirror_out(
            "excluded_channels", "channel_id", guild_id, channel_id
        )
        if self.mongo:
            await self._mongo_write(
                self._pull_array(guild_id, "excluded_channels", channel_id),
                "excluded_channels",
            )

    async def add_target_channel(self, guild_id, channel_id):
        await self._mirror_into(
            "target_channels", "guild_id, channel_id", (guild_id, channel_id)
        )
        if self.mongo:
            await self._mongo_write(
                self._push_array(guild_id, "target_channels", channel_id),
                "target_channels",
            )

    async def remove_target_channel(self, guild_id, channel_id):
        await self._mirror_out(
            "target_channels", "channel_id", guild_id, channel_id
        )
        if self.mongo:
            await self._mongo_write(
                self._pull_array(guild_id, "target_channels", channel_id),
                "target_channels",
            )

    # ── Listeners ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.id == self.bot.user.id or not message.guild:
                return

            config = await self.get_config(message.guild.id)
            if not config["delete_messages"]:
                return

            if str(message.channel.id) in config["excluded_channels"]:
                return

            content = (message.content or "").lower().strip()

            if str(message.author.id) not in config["target_users"]:
                return

            print(f"[AntiSpamPlus] Deleting msg from {message.author.id} in {message.guild.id} (tu={config['target_users']})")
            await asyncio.sleep(config["delete_delay"])
            perms = message.channel.permissions_for(message.guild.me)
            if not perms.manage_messages:
                return

            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        except Exception as e:
            print(f"AntiSpamPlus on_message error: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        try:
            if payload.user_id == self.bot.user.id:
                return

            config = await self.get_config(payload.guild_id)
            if str(payload.channel_id) not in config["target_channels"]:
                return

            now = time.time()
            if payload.user_id in self.cooldown:
                if now - self.cooldown[payload.user_id] < config["re_cooldown"]:
                    return

            data = self.user_data[payload.user_id]
            data.append((now, payload.message_id))
            while data and now - data[0][0] > config["re_window"]:
                data.popleft()

            unique_msgs = {msg_id for _, msg_id in data}
            self.message_reactions[payload.user_id][payload.message_id] += 1
            same_msg_trigger = (
                self.message_reactions[payload.user_id][payload.message_id] > 4
            )
            multi_msg_trigger = len(unique_msgs) >= config["re_limit"]

            if not (same_msg_trigger or multi_msg_trigger):
                return

            self.cooldown[payload.user_id] = now
            self.user_data[payload.user_id].clear()
            self.message_reactions[payload.user_id].clear()

            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return

            member = guild.get_member(payload.user_id)

            for ch_id in config["target_channels"]:
                channel = self.bot.get_channel(int(ch_id))
                if not channel:
                    continue
                try:
                    async for msg in channel.history(limit=150):
                        for reaction in msg.reactions:
                            try:
                                target_user = member or await self.bot.fetch_user(
                                    payload.user_id
                                )
                                await msg.remove_reaction(
                                    reaction.emoji, target_user
                                )
                                await asyncio.sleep(config["re_delay"])
                            except (discord.Forbidden, discord.NotFound):
                                pass
                            except Exception as e:
                                print(f"Reaction remove failed: {e}")
                except Exception as e:
                    print(f"Channel history failed: {e}")

        except Exception as e:
            print(f"AntiSpamPlus reaction handler error: {e}")


def setup(bot):
    bot.add_cog(AntiSpamPlus(bot))
