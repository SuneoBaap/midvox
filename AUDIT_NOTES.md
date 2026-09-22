# MidVox audit notes

This file records findings from the repository-wide audit performed on
2026-09-22. These items are intentionally deferred until the owner chooses the
next major repair. Do not silently remove features while addressing them.

## Resolved repairs

- YouTube Shorts now use the bundled Cobalt sidecar with `videoQuality=max`
  and AV1. The bot no longer sends YouTube cookies or uses its old yt-dlp and
  WARP path; Cobalt handles its own processing in the same container.

## Major issues to address deliberately

- Enforce Discord session and Manage Server authorization in the dashboard API
  proxy. Protect every guild route in the Python API as defense in depth.
- Stop exposing `DASHBOARD_API_KEY` as a `NEXT_PUBLIC_` browser variable. The
  server-side proxy should add the private credential itself.
- Establish persistent Railway storage. Current SQLite and JSON changes are
  lost on redeploy when MongoDB or a Railway volume is not configured.
- Review and clean the committed SQLite seed databases before removing them
  from Git; several contain inherited server configuration and activity data.
- Upgrade the unsupported Next.js 14.2.3 dashboard to a maintained, patched
  release with regression testing.
- Remove the upstream owner-ID fallback and fail startup when `OWNER_IDS` is
  missing or invalid.
- Restore MongoDB certificate validation; do not use
  `tlsAllowInvalidCertificates=true`.

## Minor and reliability issues to fix later

- Remove duplicate welcome and autoreact FastAPI routes.
- Replace database `eval()` calls with safe JSON or `ast.literal_eval` parsing;
  replace calculator `eval()` with an arithmetic parser.
- Move synchronous HTTP requests out of Discord's async event loop.
- Replace bare `except:` handlers with targeted errors and useful logging.
- Remove runtime dependency installation from `utils/paginators.py`.
- Make required cog-loading errors fail startup instead of continuing with a
  partially loaded bot.
- Add tests for bot startup, API authorization, database migrations, and core
  moderation commands.
- Pin Python dependencies and commit a JavaScript lockfile for reproducible
  builds.

## Audit baseline

- 951 tracked files were inventoried.
- 209 Python files parsed successfully; the removed
  `leveling_original.py` backup was the sole null-byte failure.
- 572 tracked images passed format verification.
- 39 SQLite databases passed `PRAGMA integrity_check`.
- No live Discord tokens, webhook tokens, private keys, or service credentials
  were detected in tracked text files.
