"""
Shared CV2 (Component V2) utilities for the bot.
Provides a helper to build Container objects since Container()
does NOT accept positional children arguments — items must be
added via .add_item().
"""

import discord
from discord.ui import LayoutView, TextDisplay, Separator, Container
from utils.theme import PRIMARY
from utils.emoji import CROSS, TICK, WARNING


BOT_THEME_COLOR = PRIMARY


def animate_status_icons(value):
    """Upgrade legacy status characters in CV2 text to application emojis."""
    return str(value).replace("❌", CROSS).replace("✅", TICK).replace("⚠️", WARNING).replace("⚠", WARNING)


def build_container(*items, accent_color=BOT_THEME_COLOR):
    """Build a dark-friendly Container with the MidVox olive accent."""
    container = Container(accent_color=accent_color)
    for item in items:
        container.add_item(item)
    return container


def card_text_items(title, sections):
    """Create compact text blocks without the old divider-heavy layout."""
    blocks = [f"**{animate_status_icons(title)}**"]
    blocks.extend(animate_status_icons(section) for section in sections if section not in (None, ""))
    items = []
    current = ""
    for block in blocks:
        block = str(block)
        candidate = f"{current}\n{block}" if current else block
        if len(candidate) <= 3900:
            current = candidate
            continue
        if current:
            items.append(TextDisplay(current))
        while len(block) > 3900:
            items.append(TextDisplay(block[:3900]))
            block = block[3900:]
        current = block
    if current:
        items.append(TextDisplay(current))
    return items


class CV2(LayoutView):
    """Quick helper: CV2("Title", "section1", "section2", ...)"""
    def __init__(self, title, *sections):
        super().__init__(timeout=None)
        container = build_container(*card_text_items(title, sections))
        self.add_item(container)

def add_action_rows(container, components):
    """Safely adds components to a CV2 container across multiple ActionRows"""
    from discord.ui import ActionRow
    current_row = []
    for item in components:
        if getattr(item, 'type', None) and getattr(item.type, 'value', 0) != 2:
            if current_row:
                container.add_item(ActionRow(*current_row))
                current_row = []
            container.add_item(ActionRow(item))
        else:
            current_row.append(item)
            if len(current_row) == 5:
                container.add_item(ActionRow(*current_row))
                current_row = []
    if current_row:
        container.add_item(ActionRow(*current_row))

class CV2Embed(CV2):
    """A CV2 container that behaves like a discord.Embed."""
    def __init__(self, title="", description="", **kwargs):
        self._title = title
        self._description = description or ""
        self._fields = []
        self._footer = None
        super().__init__(title, self._description)
        self.color = kwargs.get("color", BOT_THEME_COLOR)

    def _rebuild(self):
        self.clear_items()
        sections = [self._description] if self._description else []
        for name, value in self._fields:
            sections.append(f"**{name}**\n{value}")

        if self._footer:
            sections.append(f"*{self._footer}*")

        container = build_container(*card_text_items(self._title, sections), accent_color=self.color)
        self.add_item(container)

    def add_field(self, name, value, inline=False, **kwargs):
        self._fields.append((name, value))
        self._rebuild()
        return self

    def set_footer(self, text=None, icon_url=None, **kwargs):
        if text:
            self._footer = text
            self._rebuild()
        return self

    def set_thumbnail(self, url=None, **kwargs):
        return self

    def set_author(self, name=None, url=None, icon_url=None, **kwargs):
        return self

    def set_image(self, url=None, **kwargs):
        return self

    def to_dict(self):
        return {"title": self._title, "description": self._description}
