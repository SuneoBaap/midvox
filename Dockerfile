FROM node:24-bookworm-slim AS node

FROM debian:bookworm-slim AS warp_tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL --retry 3 \
        -o /usr/local/bin/wgcf \
        https://github.com/ViRb3/wgcf/releases/download/v2.2.30/wgcf_2.2.30_linux_amd64 \
    && echo 'fc443008fe29a6f0b05b45d27436b7ce89e87a6836718597ccb39e41da418304  /usr/local/bin/wgcf' | sha256sum -c - \
    && curl -fsSL --retry 3 \
        -o /tmp/wireproxy.tar.gz \
        https://github.com/windtf/wireproxy/releases/download/v1.1.3/wireproxy_linux_amd64.tar.gz \
    && echo 'e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c  /tmp/wireproxy.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/wireproxy.tar.gz -C /usr/local/bin wireproxy \
    && chmod 0755 /usr/local/bin/wgcf /usr/local/bin/wireproxy

# Use Discord's official Linux desktop client so linked account activities are
# handled by Discord itself. The tar package avoids running an installer in the
# final image and is refreshed whenever Railway rebuilds the image.
FROM debian:bookworm-slim AS discord_desktop
# The public package contains only a small updater. Install its desktop modules
# during the image build so the first deployment can authenticate and publish
# linked-account activity without a five-minute startup wait.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fL --retry 3 \
        -o /tmp/discord.tar.gz \
        'https://discord.com/api/download?platform=linux&format=tar.gz' \
    && tar -xzf /tmp/discord.tar.gz -C /opt \
    && if [ -x /opt/Discord/discord ]; then \
         ln -s discord /opt/Discord/Discord; \
       elif [ ! -x /opt/Discord/Discord ]; then \
         echo 'Discord launcher not found after extracting the Linux package' >&2; \
         exit 1; \
       fi \
    && mkdir -p /discord-home/discord \
    && /opt/Discord/updater_bootstrap --no-zenity \
         /discord-home/discord stable https://updates.discord.com/ \
    && test -n "$(find /discord-home/discord -maxdepth 2 -type f -name Discord -perm /111 -print -quit)"

# Cobalt 11.7.1 is pinned to youtubei.js 17.0.1, which is no longer reliable
# against YouTube's current player API. Keep Cobalt itself stable while using
# the current extractor in an isolated dependency tree.
FROM node:24-bookworm-slim AS youtube_extractor
WORKDIR /opt/youtube-extractor
RUN npm init -y \
    && npm install --omit=dev --ignore-scripts --no-audit --no-fund youtubei.js@18.1.0

# The Rust BotGuard provider generates PoTokens in a small memory footprint.
# Pin its image so deployments do not change underneath the bot.
FROM ghcr.io/jim60105/bgutil-pot:v0.8.1 AS youtube_session

# Run Cobalt as a local sidecar in the same Railway container. This keeps the
# deployment to one service while retaining Cobalt's own processing runtime.
FROM ghcr.io/imputnet/cobalt:11.7.1 AS cobalt

# Build and prune the dashboard outside the production image. The runtime only
# needs Node itself plus the compiled application and production dependencies.
FROM node:24-bookworm-slim AS dashboard_builder
WORKDIR /build/dashboard
COPY dashboard/package.json ./
RUN npm install --no-audit --no-fund
COPY dashboard/ ./
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG NEXT_PUBLIC_DASHBOARD_API_KEY
ARG NEXT_PUBLIC_ADMIN_IDS
ARG NEXT_PUBLIC_BRAND_NAME=MidVox
ARG NEXT_PUBLIC_BRAND_NAME_WORD=MV
ARG DISCORD_CLIENT_ID
ARG NEXT_PUBLIC_DISCORD_CLIENT_ID
RUN NEXT_PUBLIC_DISCORD_CLIENT_ID="${NEXT_PUBLIC_DISCORD_CLIENT_ID:-$DISCORD_CLIENT_ID}" npm run build \
    && npm prune --omit=dev

FROM python:3.12-slim-bookworm

# Python runs the bot, Node serves the dashboard, and the bundled Cobalt
# runtime handles YouTube Shorts inside the same container.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=warp_tools /usr/local/bin/wgcf /usr/local/bin/wgcf
COPY --from=warp_tools /usr/local/bin/wireproxy /usr/local/bin/wireproxy
COPY --from=discord_desktop /opt/Discord /opt/Discord
COPY --from=discord_desktop /discord-home /var/lib/midvox/discord-home
COPY --from=cobalt /app /opt/cobalt
COPY --from=youtube_extractor /opt/youtube-extractor/node_modules /opt/youtube-extractor/node_modules
COPY --from=youtube_session /bgutil-pot /usr/local/bin/bgutil-pot
# Point Cobalt's two extractor imports at the updated isolated package. Using
# an isolated tree avoids rewriting the pnpm-managed modules from its image.
RUN sed -i 's#from "youtubei.js"#from "file:///opt/youtube-extractor/node_modules/youtubei.js/dist/src/platform/node.js"#' \
        /opt/cobalt/src/core/env.js \
        /opt/cobalt/src/processing/services/youtube.js \
    && ! grep -R 'from "youtubei.js"' \
        /opt/cobalt/src/core/env.js \
        /opt/cobalt/src/processing/services/youtube.js \
    && node --input-type=module -e \
        'import("file:///opt/youtube-extractor/node_modules/youtubei.js/dist/src/platform/node.js").then((module) => { if (!module.Innertube) process.exit(1) })'
COPY docker/patch_cobalt_youtube.py /tmp/patch_cobalt_youtube.py
RUN python /tmp/patch_cobalt_youtube.py \
    && rm /tmp/patch_cobalt_youtube.py
# Fail during the image build if the official Cobalt API was not copied. This
# makes a Railway builder/configuration mistake visible in Build Logs.
RUN test -e /opt/cobalt/src/cobalt.js \
    || (echo 'Cobalt image was not copied: expected /opt/cobalt/src/cobalt.js' >&2; find /opt/cobalt -maxdepth 3 -type f -print >&2; exit 1)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates fonts-liberation libasound2 libatk-bridge2.0-0 \
        libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
        libatomic1 libnotify4 libnspr4 libnss3 libpulse0 libstdc++6 libx11-6 \
        libxcb1 libxcomposite1 libxdamage1 libegl1 libgl1-mesa-dri \
        libxext6 libxfixes3 libxkbcommon0 libxrandr2 libxss1 libxtst6 \
        passwd util-linux xdg-utils xvfb chromium ffmpeg \
    && useradd --system --create-home --home-dir /home/midvox --shell /usr/sbin/nologin midvox \
    && test -x /opt/Discord/discord \
    && test -n "$(find /var/lib/midvox/discord-home/discord -maxdepth 2 -type f -name Discord -perm /111 -print -quit)" \
    && command -v Xvfb \
    && DISCORD_RUNTIME="$(find /var/lib/midvox/discord-home/discord -maxdepth 2 -type f -name Discord -perm /111 -print -quit)" \
    && if ldd "$DISCORD_RUNTIME" | grep 'not found'; then exit 1; fi \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080

WORKDIR /app
COPY bot/requirements.txt bot/requirements.txt
RUN python -m pip install -r bot/requirements.txt
COPY --from=dashboard_builder /build/dashboard dashboard/
COPY bot/ bot/
COPY docker/youtube_session_server.py /opt/youtube-session/server.py
COPY docker/youtube_login_server.py /opt/youtube-session/login.py
COPY docker/youtube_session_store.py /opt/youtube-session/youtube_session_store.py
COPY start.sh start.sh
RUN test -x /usr/local/bin/bgutil-pot \
    && python -m py_compile /opt/youtube-session/server.py \
    && sed -i 's/\r$//' start.sh && bash -n start.sh

ENV NODE_ENV=production
EXPOSE 8080
CMD ["bash", "start.sh"]
