import os, re, glob
import asyncio
import aiosqlite
from motor.motor_asyncio import AsyncIOMotorClient


def _discover_db_paths():
    """Auto-discover all .db files in the db/ directory."""
    db_dir = os.path.join(os.path.dirname(__file__), "..", "db")
    if not os.path.isdir(db_dir):
        return []
    return sorted(glob.glob(os.path.join(db_dir, "*.db")))

SQLITE_DBS = _discover_db_paths() or []


def normalize_mongo_uri(uri):
    """Return a usable Mongo URI, treating Railway's empty quoted value as unset."""
    value = (uri or "").strip().strip('"').strip("'").strip()
    if not value or not value.startswith(("mongodb://", "mongodb+srv://")):
        return None
    return value


def has_valid_mongo_uri(uri=None):
    return normalize_mongo_uri(uri if uri is not None else os.getenv("MONGO_URI")) is not None

class MongoManager:
    def __init__(self, uri: str = None, db_name: str = "midvox"):
        self._uri = normalize_mongo_uri(uri if uri is not None else os.getenv("MONGO_URI"))
        self._db_name = db_name
        # motor clients are bound to the event loop they were created on.
        # The bot loop and the FastAPI (uvicorn) loop are different, so we
        # keep one client per loop and hand each caller its own.
        self._clients = {}

    def _get_client(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        client = self._clients.get(loop)
        if client is None:
            uri = self._uri
            if not uri:
                raise ValueError("MONGO_URI is not set")
            # Add TLS params if missing — Render's SSL env may not have the right CAs
            if "tls=" not in uri and "ssl=" not in uri:
                sep = "&" if "?" in uri else "?"
                uri += f"{sep}tls=true&tlsAllowInvalidCertificates=true"
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
            self._clients[loop] = client
        return client

    @property
    def _db(self):
        return self._get_client()[self._db_name]

    async def connect(self, uri: str = None, db_name: str = "midvox", server_selection_timeout: int = 10000):
        uri = normalize_mongo_uri(uri if uri is not None else os.getenv("MONGO_URI"))
        if not uri:
            raise ValueError("MONGO_URI is not set")
        # Add TLS params if missing — Render's SSL env may not have the right CAs
        if "tls=" not in uri and "ssl=" not in uri:
            sep = "&" if "?" in uri else "?"
            uri += f"{sep}tls=true&tlsAllowInvalidCertificates=true"
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=server_selection_timeout)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._clients[loop] = client
        await client.admin.command("ping")
        return self

    @property
    def antispamplus_config(self):
        return self._db["antispamplus_config"]

    @property
    def instadl_config(self):
        return self._db["instadl_config"]

    async def close(self):
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                pass

    @property
    def _sqlite_backup(self):
        return self._db["sqlite_backup"]

    @property
    def emoji_overrides(self):
        return self._db["emoji_overrides"]

    async def save_emoji_override(self, var_name: str, name: str, emoji_id: str, animated: bool = False):
        await self.emoji_overrides.replace_one(
            {"_id": var_name},
            {"_id": var_name, "name": name, "emoji_id": emoji_id, "animated": animated, "manual": True},
            upsert=True,
        )

    async def save_emoji_overrides_bulk(self, entries: list):
        """Save multiple emoji overrides at once."""
        if not entries:
            return
        from pymongo import ReplaceOne
        ops = [
            ReplaceOne(
                {"_id": e["var_name"]},
                {"_id": e["var_name"], "name": e["name"], "emoji_id": e["emoji_id"], "animated": e.get("animated", False), "manual": True},
                upsert=True,
            ) for e in entries
        ]
        await self.emoji_overrides.bulk_write(ops)

    async def delete_emoji_override(self, var_name: str):
        await self.emoji_overrides.delete_one({"_id": var_name})

    async def get_all_emoji_overrides(self):
        docs = await self.emoji_overrides.find({"manual": True}).to_list(None)
        return docs

    async def apply_emoji_overrides_to_file(self, emoji_py_path: str):
        """Apply MongoDB overrides to emoji.py (overwriting synced/default values)."""
        docs = await self.get_all_emoji_overrides()
        if not docs:
            return False
        with open(emoji_py_path, "r", encoding="utf-8") as f:
            content = f.read()
        changed = False
        for doc in docs:
            var_name = doc["_id"]
            name = doc["name"]
            eid = doc["emoji_id"]
            animated = doc.get("animated", False)
            a = "a" if animated else ""
            new_line = f'{var_name} = "<{a}:{name}:{eid}>"'
            match = re.search(rf'^{re.escape(var_name)}\s*=\s*".*?"', content, re.MULTILINE)
            if match:
                content = content[:match.start()] + new_line + content[match.end():]
                changed = True
        if changed:
            with open(emoji_py_path, "w", encoding="utf-8") as f:
                f.write(content)
        return changed

    async def backup_sqlite(self, db_path: str = None):
        """Upload a SQLite db file to MongoDB as a backup."""
        paths = [db_path] if db_path else SQLITE_DBS
        for p in paths:
            if not os.path.exists(p):
                continue
            with open(p, "rb") as f:
                data = f.read()
            name = os.path.basename(p)
            await self._sqlite_backup.replace_one(
                {"_id": name},
                {"_id": name, "data": data, "updated_at": __import__("datetime").datetime.utcnow()},
                upsert=True,
            )

    async def restore_sqlite(self, db_path: str = None):
        """Download a SQLite db file from MongoDB backup and write it to disk."""
        paths = [db_path] if db_path else SQLITE_DBS
        for p in paths:
            name = os.path.basename(p)
            doc = await self._sqlite_backup.find_one({"_id": name})
            if not doc:
                continue
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "wb") as f:
                f.write(doc["data"])
