"""Apply MidVox's compatibility fixes to the bundled Cobalt runtime.

MidVox uses this only over loopback so it can retry a Short with another
official YouTube client when one client is challenged on a datacenter IP.
Node 24's default hybrid TLS group is also unreliable through wireproxy's
HTTP CONNECT tunnel. Restrict target TLS to the broadly supported classic
groups and avoid reusing a tunnel after YouTube closes it.
The replacements are deliberately exact so a future Cobalt update fails the
Docker build instead of silently producing an unpatched image.
"""

import os
from pathlib import Path


COBALT_ROOT = Path(os.environ.get("COBALT_ROOT", "/opt/cobalt"))


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one patch location in {target}")
    target.write_text(source.replace(old, new), encoding="utf-8")


replace_once(
    str(COBALT_ROOT / "src/processing/schema.js"),
    '    youtubeBetterAudio: z.boolean().default(false),\n',
    '    youtubeBetterAudio: z.boolean().default(false),\n'
    '    youtubeClient: z.enum([\n'
    '        "IOS", "ANDROID_VR", "ANDROID", "VISIONOS", "TV_SIMPLY", "MWEB"\n'
    '    ]).optional(),\n',
)

replace_once(
    str(COBALT_ROOT / "src/processing/match.js"),
    "                    subtitleLang,\n                }\n",
    "                    subtitleLang,\n"
    "                    innertubeClient: params.youtubeClient,\n"
    "                }\n",
)

replace_once(
    str(COBALT_ROOT / "src/core/api.js"),
    "        const options = {};\n",
    "        const options = {\n"
    "            requestTls: { ecdhCurve: \"X25519:P-256\" },\n"
    "            pipelining: 0,\n"
    "            connections: 0,\n"
    "        };\n",
)

replace_once(
    str(COBALT_ROOT / "src/core/env.js"),
    "        ytSessionReloadInterval: 300,\n",
    "        ytSessionReloadInterval: "
    "(env.YOUTUBE_SESSION_RELOAD_INTERVAL "
    "&& parseInt(env.YOUTUBE_SESSION_RELOAD_INTERVAL)) || 300,\n",
)

replace_once(
    str(COBALT_ROOT / "src/processing/services/youtube.js"),
    "let innertube, lastRefreshedAt;\n",
    "let innertube, lastRefreshedAt, lastSessionUpdated;\n",
)

replace_once(
    str(COBALT_ROOT / "src/processing/services/youtube.js"),
    "    const sessionTokens = getYouTubeSession();\n"
    "    const retrieve_player = Boolean(sessionTokens || cookie);\n",
    "    const sessionTokens = getYouTubeSession();\n"
    "    const sessionChanged = useSession && sessionTokens?.updated "
    "&& sessionTokens.updated !== lastSessionUpdated;\n"
    "    const retrieve_player = Boolean(sessionTokens || cookie);\n",
)

replace_once(
    str(COBALT_ROOT / "src/processing/services/youtube.js"),
    "    if (!innertube || shouldRefreshPlayer) {\n",
    "    if (!innertube || shouldRefreshPlayer || sessionChanged) {\n",
)

replace_once(
    str(COBALT_ROOT / "src/processing/services/youtube.js"),
    "        lastRefreshedAt = +new Date();\n",
    "        lastRefreshedAt = +new Date();\n"
    "        lastSessionUpdated = sessionTokens?.updated;\n",
)

replace_once(
    str(COBALT_ROOT / "src/processing/services/youtube.js"),
    "    // iOS client doesn't have adaptive formats of resolution >1080p,\n"
    "    // so we use the WEB_EMBEDDED client instead for those cases\n"
    "    let useSession =\n"
    "        env.ytSessionServer && (\n"
    "            (\n"
    "                !useHLS\n"
    "                && innertubeClient === \"IOS\"\n"
    "                && (\n"
    "                    (quality > 1080 && o.codec !== \"h264\")\n"
    "                    || (quality > 1080 && o.codec !== \"vp9\")\n"
    "                )\n"
    "            )\n"
    "        );\n",
    "    // YouTube challenges anonymous datacenter clients even at Discord-\n"
    "    // sized qualities. Use the matching PoToken session for every\n"
    "    // non-HLS request instead of limiting it to resolutions above 1080p.\n"
    "    let useSession = Boolean(env.ytSessionServer && !useHLS);\n",
)
