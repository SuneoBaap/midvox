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

# Cobalt runs locally in this same Railway container. Its processing runtime
# stays private and the bot talks to it over loopback; no second Railway
# service or public Cobalt API key is needed.
export COBALT_API_URL="http://127.0.0.1:9000"
if [ ! -f /opt/cobalt/src/cobalt.js ]; then
  echo "FATAL: Cobalt runtime is missing from the image. Railway must build the repository Dockerfile (builder=DOCKERFILE)." >&2
  exit 1
fi

# Generate YouTube's short-lived proof-of-origin session in this same
# container. Cobalt uses it to avoid the `error.api.youtube.login` response
# that anonymous cloud requests can receive. The generator listens only on
# loopback and needs no Railway variable or public endpoint.
if [ ! -f /opt/yt-session/potoken-generator.py ]; then
  echo "FATAL: YouTube session generator is missing from the image." >&2
  exit 1
fi
export YT_SESSION_PORT="${YT_SESSION_PORT:-8081}"
echo "Starting local YouTube session generator on port $YT_SESSION_PORT..."
(
  cd /opt/yt-session || exit 1
  Xvfb :99 -ac -screen 0 "${XVFB_WHD:-1280x720x16}" -nolisten tcp > "$ROOT/yt-session-xvfb.log" 2>&1 &
  XVFB_PID=$!
  # Match the official image: give Xvfb time to create the display before
  # Nodriver launches Chromium.
  sleep 2
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "[yt-session] Xvfb failed to start:" >&2
    tail -n 40 "$ROOT/yt-session-xvfb.log" 2>/dev/null || true
  fi
  export DISPLAY=:99
  export CHROME_PATH="${CHROME_PATH:-/usr/bin/chromium}"
  while true; do
    runuser -u midvox -- env DISPLAY="$DISPLAY" CHROME_PATH="$CHROME_PATH" \
      python potoken-generator.py --bind 127.0.0.1 --port "$YT_SESSION_PORT" --chrome-path "$CHROME_PATH" 2>&1 \
      | tee -a "$ROOT/yt-session.log" \
      | grep --line-buffered -E 'WARNING|ERROR|Failed|failed|Traceback|Exception|Chromium|browser|Permission|No such' || true
    echo "[yt-session] generator exited; restarting in 5s"
    sleep 5
  done
) &
YT_SESSION_PID=$!
YT_SESSION_READY=0
# Do not hold up Railway's public port while Chromium warms up. Cobalt will
# begin using the session endpoint as soon as the first token is available.
for i in $(seq 1 10); do
  if python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:' + '${YT_SESSION_PORT}' + '/token', timeout=2); raise SystemExit(0 if r.status == 200 else 1)" > /dev/null 2>&1; then
    echo "YouTube session generator is ready."
    YT_SESSION_READY=1
    break
  fi
  if ! kill -0 "$YT_SESSION_PID" 2>/dev/null; then
    echo "WARNING: YouTube session generator exited; Cobalt may be challenged." >&2
    tail -n 100 "$ROOT/yt-session.log" 2>/dev/null \
      | grep -E 'WARNING|ERROR|Failed|failed|Traceback|Exception|Chromium|browser|Permission|No such' || true
    break
  fi
  sleep 1
done
if [ "$YT_SESSION_READY" -ne 1 ]; then
  echo "YouTube session generator is still warming up; continuing bot startup." >&2
  echo "YouTube session generator error summary:"
  tail -n 100 "$ROOT/yt-session.log" 2>/dev/null \
    | grep -E 'WARNING|ERROR|Failed|failed|Traceback|Exception|Chromium|browser|Permission|No such' || true
fi

echo "Starting local Cobalt sidecar on port 9000..."
(
  cd /opt/cobalt || exit 1
  API_URL="${COBALT_PUBLIC_URL:-http://127.0.0.1:9000/}" \
    API_PORT=9000 API_LISTEN_ADDRESS=127.0.0.1 \
    API_INSTANCE_COUNT=1 API_AUTH_REQUIRED=0 \
    YOUTUBE_SESSION_SERVER="http://127.0.0.1:${YT_SESSION_PORT}/" \
    YOUTUBE_SESSION_INNERTUBE_CLIENT=WEB_EMBEDDED \
    node src/cobalt.js > "$ROOT/cobalt.log" 2>&1
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
echo "YouTube session PID: $YT_SESSION_PID"

wait
