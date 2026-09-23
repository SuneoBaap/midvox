#!/bin/bash

# Report Python failures instead of tee's successful exit status.
set -o pipefail

cd "$(dirname "$0")" || exit 1

echo "=== Starting MidVox ==="

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
# Copying emojis from another application is optional and may fail with 403s.
export EMOJI_SYNC="${EMOJI_SYNC:-false}"

ROOT="$(pwd)"

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

# ── One-time emoji sync (before bot starts, patches emoji.py) ─
if [ "${EMOJI_SYNC,,}" = "true" ]; then
  echo "Running one-time emoji sync..."
  (cd "$ROOT/bot" && timeout 120 python sync_emojis_once.py)
  echo "--- Emoji sync exit code: $? ---"
else
  echo "Emoji sync disabled; continuing to bot startup."
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

# Start Next.js dashboard on Render's public PORT
cd dashboard
echo "Starting dashboard on port $PORT..."
npx next start -p $PORT -H 0.0.0.0 &
DASHBOARD_PID=$!

echo "=== MidVox running ==="
echo "Bot PID: $BOT_PID"
echo "Dashboard PID: $DASHBOARD_PID"
echo "Cobalt PID: $COBALT_PID"
if [ -n "${WARP_PID:-}" ]; then
  echo "WARP PID: $WARP_PID"
fi

wait
