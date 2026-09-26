import os
import sys
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "utils", "security_heat.py"
)
SPEC = importlib.util.spec_from_file_location("security_heat", MODULE_PATH)
security_heat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security_heat)
calculate_message_heat = security_heat.calculate_message_heat
emoji_count = security_heat.emoji_count
link_count = security_heat.link_count


def message(content="", **overrides):
    values = {
        "content": content,
        "mentions": [],
        "role_mentions": [],
        "mention_everyone": False,
        "attachments": [],
        "embeds": [],
        "stickers": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class SecurityHeatTests(unittest.TestCase):
    def test_repeated_rapid_message_is_high_risk(self):
        state = {"last_message_at": 100.0, "last_content": "join my server"}
        heat, reasons = calculate_message_heat(
            message("join my server"), state, 100.5
        )
        self.assertGreaterEqual(heat, 60)
        self.assertIn("rapid messages", reasons)
        self.assertIn("repeated content", reasons)

    def test_mass_mentions_cross_default_threshold(self):
        heat, reasons = calculate_message_heat(
            message("@everyone", mention_everyone=True, mentions=[1]), {}, 100
        )
        self.assertGreaterEqual(heat, 100)
        self.assertIn("public mention", reasons)

    def test_links_custom_emoji_and_unicode_emoji_are_counted(self):
        self.assertEqual(link_count("https://a.test discord.gg/example"), 2)
        self.assertEqual(emoji_count("<a:dance:123> 😀 🔥"), 3)

    def test_normal_message_stays_low_risk(self):
        heat, reasons = calculate_message_heat(message("hello everyone"), {}, 100)
        self.assertEqual(heat, 7)
        self.assertEqual(reasons, [])

    def test_antinuke_listeners_do_not_black_out_during_bursts(self):
        antinuke_dir = Path(__file__).parents[1] / "cogs" / "antinuke"
        for module in antinuke_dir.glob("*.py"):
            self.assertNotIn(
                "if not self.can_fetch_audit",
                module.read_text(encoding="utf-8"),
                f"{module.name} still disables protection during rapid events",
            )
            self.assertNotIn(
                "audit_logs(action=action, limit=1)",
                module.read_text(encoding="utf-8"),
                f"{module.name} only checks one audit entry during bursts",
            )

        for filename in ("antiwebhookcr.py", "antiwebhookdl.py"):
            self.assertIn(
                "on_webhooks_update",
                (antinuke_dir / filename).read_text(encoding="utf-8"),
                f"{filename} is not listening to Discord's webhook update event",
            )


if __name__ == "__main__":
    unittest.main()
