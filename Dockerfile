FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

# Both runtimes are required: Python runs the bot and Node serves the dashboard.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl ffmpeg \
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
