"""Make the bundled YouTube session generator safe for MidVox on Railway.

The generator's Chromium must use the same WARP exit as Cobalt or YouTube
rejects the proof token.  The upstream program does not expose a proxy option,
so this build-time patch reads one from ``YT_SESSION_PROXY``.  Exact matches
make an upstream image change fail the build instead of silently bypassing the
proxy.  Token values are never written to Railway logs.
"""

import os
from pathlib import Path


SESSION_ROOT = Path(os.environ.get("YT_SESSION_ROOT", "/opt/yt-session"))
EXTRACTOR = SESSION_ROOT / "potoken_generator/extractor.py"


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one session-generator patch for {old!r}")
    return source.replace(old, new)


text = EXTRACTOR.read_text(encoding="utf-8")
text = replace_once(text, "import logging\n", "import logging\nimport os\n")
text = replace_once(
    text,
    """                browser = await nodriver.start(headless=False,
                                               browser_executable_path=self.browser_path,
                                               user_data_dir=self.profile_path)
""",
    """                browser_args = []
                proxy = os.environ.get('YT_SESSION_PROXY', '').strip()
                if proxy:
                    browser_args.append(f'--proxy-server={proxy}')
                browser = await nodriver.start(headless=False,
                                               browser_executable_path=self.browser_path,
                                               user_data_dir=self.profile_path,
                                               browser_args=browser_args,
                                               sandbox=False)
""",
)
text = replace_once(
    text,
    "        logger.info(f'new token: {token_info.to_json()}')\n",
    "        logger.info('new YouTube session token generated')\n",
)
EXTRACTOR.write_text(text, encoding="utf-8")
