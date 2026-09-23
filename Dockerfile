FROM node:24-bookworm-slim AS node

# Cobalt 11.7.1 is pinned to youtubei.js 17.0.1, which is no longer reliable
# against YouTube's current player API. Keep Cobalt itself stable while using
# the current extractor in an isolated dependency tree.
FROM node:24-bookworm-slim AS youtube_extractor
WORKDIR /opt/youtube-extractor
RUN npm init -y \
    && npm install --omit=dev --ignore-scripts --no-audit --no-fund youtubei.js@18.1.0

# Run Cobalt as a local sidecar in the same Railway container. This keeps the
# deployment to one service while retaining Cobalt's own processing runtime.
FROM ghcr.io/imputnet/cobalt:11.7.1 AS cobalt

FROM python:3.12-slim-bookworm

# Python runs the bot, Node serves the dashboard, and the bundled Cobalt
# runtime handles YouTube Shorts inside the same container.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=cobalt /app /opt/cobalt
COPY --from=youtube_extractor /opt/youtube-extractor/node_modules /opt/youtube-extractor/node_modules
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
# Fail during the image build if the official Cobalt API was not copied. This
# makes a Railway builder/configuration mistake visible in Build Logs.
RUN test -e /opt/cobalt/src/cobalt.js \
    || (echo 'Cobalt image was not copied: expected /opt/cobalt/src/cobalt.js' >&2; find /opt/cobalt -maxdepth 3 -type f -print >&2; exit 1)
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080

WORKDIR /app
COPY bot/requirements.txt bot/requirements.txt
RUN python -m pip install -r bot/requirements.txt

COPY dashboard/package.json dashboard/package.json
RUN cd dashboard && npm install --no-audit --no-fund

COPY dashboard/ dashboard/
# Next.js embeds public variables during the build. Railway supplies these args.
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG NEXT_PUBLIC_DASHBOARD_API_KEY
ARG NEXT_PUBLIC_ADMIN_IDS
ARG NEXT_PUBLIC_BRAND_NAME=MidVox
ARG NEXT_PUBLIC_BRAND_NAME_WORD=MV
ARG DISCORD_CLIENT_ID
ARG NEXT_PUBLIC_DISCORD_CLIENT_ID
RUN cd dashboard \
    && NEXT_PUBLIC_DISCORD_CLIENT_ID="${NEXT_PUBLIC_DISCORD_CLIENT_ID:-$DISCORD_CLIENT_ID}" npm run build \
    && npm prune --omit=dev

COPY bot/ bot/
COPY start.sh start.sh
RUN sed -i 's/\r$//' start.sh && bash -n start.sh

ENV NODE_ENV=production
EXPOSE 8080
CMD ["bash", "start.sh"]
