"""Expose Cobalt's internal Innertube client selector to the local API.

MidVox uses this only over loopback so it can retry a Short with another
official YouTube client when one client is challenged on a datacenter IP.
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
