FROM node:24-bookworm-slim AS node

# Run Cobalt as a local sidecar in the same Railway container. This keeps the
# deployment to one service while retaining Cobalt's own processing runtime.
FROM ghcr.io/imputnet/cobalt:11.7.1 AS cobalt

# Cobalt's YouTube extractor can be challenged by YouTube when it runs from a
# cloud IP. The official session generator supplies fresh po_token and
# visitor_data values over localhost. It is copied into this same image (not a
# second Railway service) and started by start.sh.
FROM ghcr.io/imputnet/yt-session-generator:webserver AS yt_session

FROM python:3.12-slim-bookworm

# Python runs the bot, Node serves the dashboard, and the bundled Cobalt
# runtime handles YouTube Shorts inside the same container.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=cobalt /app /opt/cobalt
COPY --from=yt_session /app /opt/yt-session
# Fail during the image build if the official Cobalt API was not copied. This
# makes a Railway builder/configuration mistake visible in Build Logs.
RUN test -e /opt/cobalt/src/cobalt.js \
    || (echo 'Cobalt image was not copied: expected /opt/cobalt/src/cobalt.js' >&2; find /opt/cobalt -maxdepth 3 -type f -print >&2; exit 1)
RUN test -f /opt/yt-session/potoken-generator.py \
    || (echo 'YouTube session generator was not copied into the image' >&2; find /opt/yt-session -maxdepth 3 -type f -print >&2; exit 1)
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates chromium chromium-driver xvfb passwd util-linux \
    && useradd --system --create-home --home-dir /home/midvox --shell /usr/sbin/nologin midvox \
    && chown -R midvox:midvox /opt/yt-session \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080

WORKDIR /app
COPY bot/requirements.txt bot/requirements.txt
RUN python -m pip install -r bot/requirements.txt
COPY --from=yt_session /app/requirements.txt yt-session-requirements.txt
RUN python -m pip install -r yt-session-requirements.txt
# Match the official session-generator image's Chromium startup workaround.
RUN sed -i 's/await self.sleep(0.5)/await self.sleep(2)/' \
    /usr/local/lib/python3.12/site-packages/nodriver/core/browser.py
# Railway does not expose the kernel features Chromium needs for its sandbox.
# This applies only to the private token-generator browser, which still runs
# as the unprivileged `midvox` user and listens only on loopback.
RUN sed -i 's/nodriver.start(headless=False,/nodriver.start(headless=False, sandbox=False,/' \
    /opt/yt-session/potoken_generator/extractor.py \
    && grep -q 'nodriver.start(headless=False, sandbox=False,' \
    /opt/yt-session/potoken_generator/extractor.py

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
