#!/bin/bash

# Report Python failures instead of tee's successful exit status.
set -o pipefail

cd "$(dirname "$0")" || exit 1

echo "=== Starting MidVox ==="

# Railway changes the public hostname when this project is cloned to another
# account. Always prefer Railway's live hostname over a copied NEXTAUTH_URL so
# Discord OAuth cannot redirect to an older deployment.
if [ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ]; then
  export NEXTAUTH_URL="https://${RAILWAY_PUBLIC_DOMAIN%/}"
  echo "Dashboard OAuth URL: $NEXTAUTH_URL"
fi

# A Discord bot token identifies its application in the token's first segment.
# Use that runtime identity for OAuth and invites so copied Railway variables
# cannot leave the dashboard connected to a previous bot application.
TOKEN_CLIENT_ID="$(python -c 'import base64, os; part=os.environ.get("TOKEN", "").split(".", 1)[0]; print(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode() if part else "")' 2>/dev/null || true)"
if printf '%s' "$TOKEN_CLIENT_ID" | grep -Eq '^[0-9]+$'; then
  if [ -n "${DISCORD_CLIENT_ID:-}" ] && [ "$DISCORD_CLIENT_ID" != "$TOKEN_CLIENT_ID" ]; then
    echo "WARNING: DISCORD_CLIENT_ID did not match TOKEN; using the active bot application ID." >&2
  fi
  export DISCORD_CLIENT_ID="$TOKEN_CLIENT_ID"
  export NEXT_PUBLIC_DISCORD_CLIENT_ID="$TOKEN_CLIENT_ID"
  echo "Discord application ID: $DISCORD_CLIENT_ID"
fi

# Fail before starting long-lived sidecars when Railway is missing required
# runtime configuration. NEXT_PUBLIC_DASHBOARD_API_KEY remains required until
# the dashboard proxy is migrated fully to a private server-side credential.
REQUIRED_ENV=(
  TOKEN OWNER_IDS DASHBOARD_API_KEY NEXT_PUBLIC_DASHBOARD_API_KEY
  NEXTAUTH_SECRET DISCORD_CLIENT_ID DISCORD_CLIENT_SECRET
)
MISSING_ENV=()
for variable in "${REQUIRED_ENV[@]}"; do
  if [ -z "${!variable:-}" ]; then
    MISSING_ENV+=("$variable")
  fi
done
if [ "${#MISSING_ENV[@]}" -gt 0 ]; then
  echo "FATAL: Missing required environment variables: ${MISSING_ENV[*]}" >&2
  exit 1
fi

# Add Node.js binary to PATH (extracted during build into .node/)
export PATH="$(dirname "$0")/.node/bin:$PATH"

# Fail deployment immediately when the image is missing required runtimes.
for runtime in python node npx; do
  if ! command -v "$runtime" >/dev/null 2>&1; then
    echo "FATAL: $runtime is missing. Build from the repository-root Dockerfile." >&2
    exit 1
  fi
done
if [ ! -f dashboard/.next/BUILD_ID ]; then
  echo "FATAL: Dashboard is not built. Build from the repository-root Dockerfile." >&2
  exit 1
fi

export PORT="${PORT:-8080}"
export PYTHONUNBUFFERED=1

export API_ENABLED=true
export API_PORT=5001
export TUNNEL_ENABLED=false

ROOT="$(pwd)"

# Start the official user-account desktop before WARP, Cobalt, the application
# bot, and the dashboard. Wait for its authenticated Gateway READY event before
# starting any other service.
export USER_DESKTOP_READY_FILE=/tmp/midvox-user-desktop-ready
rm -f "$USER_DESKTOP_READY_FILE"
if [ -n "${USER_TOKEN:-}" ]; then
  DESKTOP_BIN="${DISCORD_DESKTOP_BIN:-/opt/Discord/discord}"
  if [ ! -x "$DESKTOP_BIN" ] && [ -x /opt/Discord/Discord ]; then
    DESKTOP_BIN=/opt/Discord/Discord
  fi
  if ! command -v Xvfb >/dev/null 2>&1 || [ ! -x "$DESKTOP_BIN" ]; then
    echo "FATAL: USER_TOKEN requires the Docker image's Discord desktop and Xvfb." >&2
    exit 1
  fi
  export DISCORD_DESKTOP_BIN="$DESKTOP_BIN"
  echo "Starting official user-account desktop first..."
  (
    while true; do
      cd "$ROOT/bot" || { echo "FATAL: bot/ directory not found at $ROOT/bot"; exit 1; }
      python bump_sidecar.py 2>&1 | tee "$ROOT/bump.log"
      echo "WARNING: User presence sidecar exited (code $?). Restarting in 5s..." >&2
      cd "$ROOT"
      rm -f "$USER_DESKTOP_READY_FILE"
      sleep 5
    done
  ) &
  BUMP_PID=$!

  echo "Waiting for official user desktop Gateway READY..."
  for i in $(seq 1 120); do
    if [ -f "$USER_DESKTOP_READY_FILE" ]; then
      echo "Official user desktop is online; starting remaining services."
      break
    fi
    if ! kill -0 "$BUMP_PID" 2>/dev/null; then
      echo "FATAL: User presence sidecar exited before becoming ready." >&2
      exit 1
    fi
    sleep 1
  done
  if [ ! -f "$USER_DESKTOP_READY_FILE" ]; then
    echo "FATAL: User desktop or Linux Desktop fallback did not become ready within 120 seconds." >&2
    tail -n 40 "$ROOT/bump.log" 2>/dev/null || true
    exit 1
  fi
else
  echo "User presence sidecar skipped (set USER_TOKEN to enable)."
  BUMP_PID=""
fi

# Railway's datacenter egress is rejected by YouTube even with valid cookies.
# Run a userspace Cloudflare WARP tunnel in this same container and expose an
# HTTP CONNECT proxy only to Cobalt. Discord and the dashboard stay direct.
setup_warp() {
  local warp_dir="/tmp/midvox-warp"
  local proxy_port="33211"
  mkdir -p "$warp_dir" || return 1

  (
    cd "$warp_dir" || exit 1
    if [ ! -s wgcf-profile.conf ]; then
      wgcf register --accept-tos || exit 1
      wgcf generate || exit 1
    fi

    cat > wireproxy.conf <<EOF
WGConfig = $warp_dir/wgcf-profile.conf

[http]
BindAddress = 127.0.0.1:$proxy_port
EOF

    exec wireproxy -c wireproxy.conf
  ) > "$warp_dir/wireproxy.log" 2>&1 &
  WARP_PID=$!

  for i in $(seq 1 25); do
    if python -c "import urllib.request; proxy='http://127.0.0.1:$proxy_port'; opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy})); trace=opener.open('https://www.cloudflare.com/cdn-cgi/trace', timeout=3).read(); assert b'warp=on' in trace or b'warp=plus' in trace" >/dev/null 2>&1; then
      export COBALT_PROXY_URL="http://127.0.0.1:$proxy_port"
      echo "WARP egress ready for Cobalt on 127.0.0.1:$proxy_port."
      return 0
    fi
    if ! kill -0 "$WARP_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done

  echo "WARNING: WARP egress failed; Cobalt will use Railway's direct IP." >&2
  tail -n 20 "$warp_dir/wireproxy.log" 2>/dev/null || true
  unset COBALT_PROXY_URL
  return 1
}

if [ "${WARP:-1}" = "1" ]; then
  setup_warp || true
else
  echo "WARP egress disabled via WARP=${WARP}."
fi

# Cobalt runs locally in this same Railway container. Its processing runtime
# stays private and the bot talks to it over loopback; no second Railway
# service or public Cobalt API key is needed.
export COBALT_API_URL="http://127.0.0.1:9000"
if [ ! -f /opt/cobalt/src/cobalt.js ]; then
  echo "FATAL: Cobalt runtime is missing from the image. Railway must build the repository Dockerfile (builder=DOCKERFILE)." >&2
  exit 1
fi

# YouTube frequently challenges datacenter IPs. When a cookie header is supplied
# as a Railway secret, convert it to Cobalt's cookies.json format at runtime.
# The secret is never committed or printed. A complete Cobalt JSON object is
# accepted too, which makes rotating an existing cookies.json straightforward.
export COBALT_COOKIE_FILE="/tmp/midvox-cobalt-cookies.json"
if [ -n "${YOUTUBE_COOKIE:-}" ]; then
  python -c 'import json, os; raw = os.environ["YOUTUBE_COOKIE"].strip(); data = json.loads(raw) if raw.startswith("{") else {"youtube": [raw]}; entries = data.get("youtube") if isinstance(data, dict) else None; assert isinstance(entries, list) and entries and all(isinstance(item, str) and item.strip() for item in entries), "YOUTUBE_COOKIE must be a cookie header or Cobalt cookies.json"; json.dump(data, open(os.environ["COBALT_COOKIE_FILE"], "w", encoding="utf-8"))' \
    || { echo "FATAL: YOUTUBE_COOKIE is empty or invalid." >&2; exit 1; }
  chmod 600 "$COBALT_COOKIE_FILE"
  export COOKIE_PATH="$COBALT_COOKIE_FILE"
  echo "Cobalt YouTube cookies: enabled."
else
  unset COOKIE_PATH
  echo "Cobalt YouTube cookies: not configured."
fi
export COBALT_YOUTUBE_CLIENT="${COBALT_YOUTUBE_CLIENT:-ANDROID_VR}"
echo "Cobalt YouTube client: $COBALT_YOUTUBE_CLIENT"

echo "Starting local Cobalt sidecar on port 9000..."
(
  cd /opt/cobalt || exit 1
  if [ -n "${COBALT_PROXY_URL:-}" ]; then
    export HTTP_PROXY="$COBALT_PROXY_URL"
    export HTTPS_PROXY="$COBALT_PROXY_URL"
    export NO_PROXY="127.0.0.1,localhost"
  fi
    API_URL="${COBALT_PUBLIC_URL:-http://127.0.0.1:9000/}" \
    API_PORT=9000 API_LISTEN_ADDRESS=127.0.0.1 \
    API_INSTANCE_COUNT=1 API_AUTH_REQUIRED=0 \
    CUSTOM_INNERTUBE_CLIENT="$COBALT_YOUTUBE_CLIENT" \
    node src/cobalt.js 2>&1 | tee "$ROOT/cobalt.log"
) &
COBALT_PID=$!
for i in $(seq 1 30); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/', timeout=1)" > /dev/null 2>&1; then
    echo "Cobalt sidecar is ready."
    break
  fi
  if ! kill -0 "$COBALT_PID" 2>/dev/null; then
    echo "FATAL: Cobalt sidecar exited. Log tail:"
    tail -n 30 "$ROOT/cobalt.log" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done
if ! python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/', timeout=2)" > /dev/null 2>&1; then
  echo "FATAL: Cobalt sidecar did not become ready. Log tail:"
  tail -n 30 "$ROOT/cobalt.log" 2>/dev/null || true
  exit 1
fi

# ── Application emoji sync ──────────────────────────────────────────
# Every Discord application owns its emoji IDs. Sync before importing cogs so
# commands work immediately when TOKEN changes to a newly-created bot account.
echo "Syncing MidVox application emojis..."
(cd "$ROOT/bot" && timeout 180 python sync_emojis_once.py)
EMOJI_SYNC_EXIT=$?
if [ "$EMOJI_SYNC_EXIT" -eq 124 ]; then
  echo "WARNING: Emoji sync timed out; commands will use any icons synced so far." >&2
elif [ "$EMOJI_SYNC_EXIT" -ne 0 ]; then
  echo "WARNING: Emoji sync failed (code $EMOJI_SYNC_EXIT); bot startup will continue." >&2
fi

# Run bot in a restart loop so if it crashes the API stays up
(
  ROOT="$(pwd)"
  while true; do
    cd "$ROOT/bot" || { echo "FATAL: bot/ directory not found at $ROOT/bot"; exit 1; }
    echo "Starting bot (API on port 5001)..."
    python CodeX.py 2>&1 | tee "$ROOT/bot.log"
    echo "WARNING: Bot exited (code $?). Restarting in 2s..." >&2
    cd "$ROOT"
    sleep 2
  done
) &
BOT_PID=$!

# Wait for bot API to be ready (just check port is open)
echo "Waiting for bot API on port 5001..."
for i in $(seq 1 30); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/health')" > /dev/null 2>&1; then
    echo "Bot API is ready!"
    break
  fi
  echo "  Attempt $i/30..."
  sleep 2
done

# Start Next.js dashboard on Railway/Render's public PORT.
cd dashboard
echo "Starting dashboard on port $PORT..."
npx next start -p "$PORT" -H 0.0.0.0 &
DASHBOARD_PID=$!

echo "=== MidVox running ==="
echo "Bot PID: $BOT_PID"
echo "Dashboard PID: $DASHBOARD_PID"
echo "Cobalt PID: $COBALT_PID"
if [ -n "${BUMP_PID:-}" ]; then
  echo "User presence sidecar PID: $BUMP_PID"
fi
if [ -n "${WARP_PID:-}" ]; then
  echo "WARP PID: $WARP_PID"
fi

# Keep the container attached to all top-level services and forward Railway's
# termination signal to the remaining processes during a deploy.
stop_services() {
  for pid in \
    "${COBALT_PID:-}" "${BOT_PID:-}" "${BUMP_PID:-}" \
    "${DASHBOARD_PID:-}" "${WARP_PID:-}"; do
    if [ -n "$pid" ]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap 'stop_services; exit 0' TERM INT

# Keep the container attached to all long-running services. Individual bot and
# sidecar components already have their own restart loops; exiting on the first
# completed background job can incorrectly terminate a healthy deployment
# during process hand-off.
wait
