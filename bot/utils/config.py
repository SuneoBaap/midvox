import os
from dotenv import load_dotenv

load_dotenv()

TOKEN      = os.environ.get("TOKEN")
BRAND_NAME = os.environ.get("brand_name", "MidVox")
NAME       = BRAND_NAME
BotName    = BRAND_NAME

PROJECT_URL = os.getenv("PROJECT_URL", "https://github.com/suneo779/midvox")
SUPPORT_URL = os.getenv("SUPPORT_URL", PROJECT_URL)

# Compatibility aliases used by older command modules.
server = SUPPORT_URL
serverLink = SUPPORT_URL

CMD_WEBHOOK_URL = os.getenv("CMD_WEBHOOK_URL")

# ── Owner / Staff IDs ─────────────────────────────────────────────────────────
# Edit OWNER_IDS in .env — comma-separated, no spaces needed.
# Example:  OWNER_IDS = 870179991462236170,767979794411028491,1432771000629596225

def _parse_ids(env_key: str, defaults: list[int]) -> list[int]:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return defaults
    ids = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
    return ids or defaults

OWNER_IDS:     list[int] = _parse_ids("OWNER_IDS",     [870179991462236170])
OWNER_IDS_STR: list[str] = [str(i) for i in OWNER_IDS]

# Aliases kept for backwards compatibility with files that import these names
BOT_OWNER_IDS     = OWNER_IDS
BOT_OWNER_IDS_STR = OWNER_IDS_STR
STAFF_IDS         = OWNER_IDS
STAFF_IDS_STR     = OWNER_IDS_STR
