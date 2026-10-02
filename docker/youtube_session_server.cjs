'use strict';

const http = require('http');
const { generate } = require('youtube-po-token-generator');

const host = process.env.YT_SESSION_HOST || '127.0.0.1';
const port = Number(process.env.YT_SESSION_PORT || 8081);
const refreshMs = Math.max(60_000, Number(process.env.YT_SESSION_REFRESH_MS || 300_000));

let cached = null;
let generation = null;

async function refresh() {
  if (generation) return generation;
  generation = (async () => {
    const result = await generate();
    if (!result || typeof result.poToken !== 'string' || !result.poToken ||
        typeof result.visitorData !== 'string' || !result.visitorData) {
      throw new Error('generator returned an incomplete YouTube session');
    }
    cached = {
      poToken: result.poToken,
      contentBinding: result.visitorData,
      potoken: result.poToken,
      visitor_data: result.visitorData,
      updated: Math.floor(Date.now() / 1000),
    };
    console.log('[yt-session] refreshed YouTube session token');
    return cached;
  })().finally(() => { generation = null; });
  return generation;
}

function sendJson(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

const server = http.createServer(async (request, response) => {
  try {
    const path = new URL(request.url, `http://${host}:${port}`).pathname;
    if ((path === '/get_pot' && request.method === 'POST') ||
        (path === '/token' && request.method === 'GET')) {
      sendJson(response, 200, cached || await refresh());
      return;
    }
    if (path === '/update' && ['GET', 'POST'].includes(request.method)) {
      sendJson(response, 200, await refresh());
      return;
    }
    if (path === '/health') {
      sendJson(response, cached ? 200 : 503, { ready: Boolean(cached) });
      return;
    }
    sendJson(response, 404, { error: 'not_found' });
  } catch (error) {
    console.error(`[yt-session] generation failed: ${error.message}`);
    sendJson(response, 503, { error: 'session_generation_failed' });
  }
});

server.listen(port, host, async () => {
  console.log(`[yt-session] listening on http://${host}:${port}`);
  try { await refresh(); } catch (error) {
    console.error(`[yt-session] initial generation failed: ${error.message}`);
  }
});

const timer = setInterval(() => {
  refresh().catch(error => console.error(`[yt-session] scheduled refresh failed: ${error.message}`));
}, refreshMs);
timer.unref();

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5_000).unref();
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
