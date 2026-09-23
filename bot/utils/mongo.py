import os, re, glob
import asyncio
import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient


BOT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_PATTERNS = (
    "db/*.db",
    "*.db",
    "db/*.json",
    "jsondb/*.json",
)


def _discover_state_paths():
    """Find every mutable settings file used by the legacy cogs."""
    paths = set()
    for pattern in STATE_PATTERNS:
        paths.update(glob.glob(os.path.join(BOT_ROOT, pattern)))
    return sorted(path for path in paths if os.path.isfile(path))


def _state_key(path):
    return os.path.relpath(os.path.abspath(path), BOT_ROOT).replace(os.sep, "/")


def _safe_state_path(key):
    candidate = os.path.abspath(os.path.join(BOT_ROOT, key.replace("/", os.sep)))
    try:
        inside_root = os.path.commonpath((BOT_ROOT, candidate)) == BOT_ROOT
    except ValueError:
        inside_root = False
    return candidate if inside_root else None


def _read_consistent_state(path):
    """Read a settings file, snapshotting SQLite through its backup API.

    Reading a live SQLite file as raw bytes can miss WAL data or upload a
    torn database. SQLite's backup API produces a consistent online snapshot.
    """
    if not path.lower().endswith(".db"):
        with open(path, "rb") as state_file:
            data = state_file.read()
        # Never replace the online copy with a half-written JSON document.
        json.loads(data.decode("utf-8-sig"))
        return data

    fd, snapshot_path = tempfile.mkstemp(prefix="midvox-state-", suffix=".db")
    os.close(fd)
    source = target = None
    try:
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        target = sqlite3.connect(snapshot_path)
        source.backup(target)
        target.close()
        target = None
        source.close()
        source = None
        with open(snapshot_path, "rb") as state_file:
            return state_file.read()
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        try:
            os.remove(snapshot_path)
        except OSError:
            pass


def normalize_mongo_uri(uri):
    """Return a usable Mongo URI, treating Railway's empty quoted value as unset."""
    value = (uri or "").strip().strip('"').strip("'").strip()
    if not value or not value.startswith(("mongodb://", "mongodb+srv://")):
        return None
    return value


def has_valid_mongo_uri(uri=None):
    return normalize_mongo_uri(uri if uri is not None else os.getenv("MONGO_URI")) is not None


def _tls_mongo_uri(uri):
    """Enable TLS without disabling certificate verification."""
    if "tls=" not in uri and "ssl=" not in uri:
        separator = "&" if "?" in uri else "?"
        return f"{uri}{separator}tls=true"
    return uri

class MongoManager:
    def __init__(self, uri: str = None, db_name: str = "midvox"):
        self._uri = normalize_mongo_uri(uri if uri is not None else os.getenv("MONGO_URI"))
        self._db_name = db_name
        # motor clients are bound to the event loop they were created on.
        # The bot loop and the FastAPI (uvicorn) loop are different, so we
        # keep one client per loop and hand each caller its own.
        self._clients = {}
        self._state_hashes = {}

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
            uri = _tls_mongo_uri(uri)
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
        uri = _tls_mongo_uri(uri)
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
    def state_files(self):
        return self._db["state_files"]

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

    async def backup_state(self, force=False):
        """Sync changed guild databases and JSON settings to MongoDB.

        MongoDB is the durable source of truth. Files in the Railway
        container are only a runtime cache for cogs that still use SQLite.
        """
        changed = 0
        for path in _discover_state_paths():
            try:
                data = await asyncio.to_thread(_read_consistent_state, path)
                digest = hashlib.sha256(data).hexdigest()
                key = _state_key(path)
                if not force and self._state_hashes.get(key) == digest:
                    continue
                await self.state_files.replace_one(
                    {"_id": key},
                    {
                        "_id": key,
                        "data": data,
                        "sha256": digest,
                        "kind": "sqlite" if path.lower().endswith(".db") else "json",
                        "updated_at": datetime.now(timezone.utc),
                    },
                    upsert=True,
                )
                self._state_hashes[key] = digest
                changed += 1
            except Exception as exc:
                print(f"[MongoState] backup failed for {_state_key(path)}: {exc}")
        return changed

    async def restore_state(self):
        """Restore all online settings before any bot cogs open their DBs."""
        docs = await self.state_files.find({}).to_list(length=None)
        restored = 0
        for doc in docs:
            key = str(doc.get("_id", ""))
            path = _safe_state_path(key)
            data = doc.get("data")
            if not path or data is None:
                continue
            data = bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            if doc.get("sha256") and doc["sha256"] != digest:
                print(f"[MongoState] skipped corrupt remote state: {key}")
                continue
            if key.lower().endswith(".json"):
                try:
                    json.loads(data.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    print(f"[MongoState] skipped invalid remote JSON: {key}")
                    continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temp_path = f"{path}.restore-{os.getpid()}"
            with open(temp_path, "wb") as state_file:
                state_file.write(data)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temp_path, path)
            self._state_hashes[key] = digest
            restored += 1

        # Import backups made by the previous implementation once. This keeps
        # existing guild settings when the new online state store is enabled.
        if not docs:
            legacy_docs = await self._sqlite_backup.find({}).to_list(length=None)
            for doc in legacy_docs:
                name = os.path.basename(str(doc.get("_id", "")))
                path = _safe_state_path(f"db/{name}")
                data = doc.get("data")
                if not path or not name.endswith(".db") or data is None:
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as state_file:
                    state_file.write(bytes(data))
                restored += 1
            if legacy_docs:
                await self.backup_state(force=True)
        return restored

    # Compatibility wrappers for older callers.
    async def backup_sqlite(self, db_path: str = None):
        if db_path:
            data = await asyncio.to_thread(_read_consistent_state, db_path)
            key = _state_key(db_path)
            digest = hashlib.sha256(data).hexdigest()
            await self.state_files.replace_one(
                {"_id": key},
                {"_id": key, "data": data, "sha256": digest,
                 "kind": "sqlite", "updated_at": datetime.now(timezone.utc)},
                upsert=True,
            )
            self._state_hashes[key] = digest
            return 1
        return await self.backup_state()

    async def restore_sqlite(self, db_path: str = None):
        if db_path:
            key = _state_key(db_path)
            doc = await self.state_files.find_one({"_id": key})
            if not doc:
                return 0
            path = _safe_state_path(key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as state_file:
                state_file.write(bytes(doc["data"]))
            return 1
        return await self.restore_state()
