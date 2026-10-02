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
SERVER = SESSION_ROOT / "potoken_generator/server.py"


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
text = replace_once(
    text,
    """            tab = browser.main_tab
            tab.add_handler(nodriver.cdp.network.RequestWillBeSent, self._send_handler)
            await tab.get('https://www.youtube.com/embed/jNQXAC9IVRw')
            player_clicked = await self._click_on_player(tab)
            if player_clicked:
                await self._wait_for_handler()
            await tab.close()
""",
    """            tab = browser.main_tab
            tab.add_handler(nodriver.cdp.network.RequestWillBeSent, self._send_handler)
            for player_url in (
                'https://www.youtube.com/embed/jNQXAC9IVRw?autoplay=1',
                'https://www.youtube.com/watch?v=jNQXAC9IVRw',
            ):
                await tab.get(player_url)
                player_clicked = await self._click_on_player(tab)
                if player_clicked and await self._wait_for_handler():
                    break
            await tab.close()
""",
)
EXTRACTOR.write_text(text, encoding="utf-8")

# Cobalt 11.7.1 requests the newer POST /get_pot endpoint while the bundled
# generator still exposes only /token. Both routes return the same JSON shape,
# and Cobalt already accepts the generator's potoken/visitor_data field names.
server_text = SERVER.read_text(encoding="utf-8")
server_text = replace_once(
    server_text,
    "            '/token': self.get_potoken,\n",
    "            '/token': self.get_potoken,\n"
    "            '/get_pot': self.get_potoken,\n",
)
SERVER.write_text(server_text, encoding="utf-8")
