import difflib
import re


EMOJI_PATTERN = re.compile(
    r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF\u2600-\u27BF]"
)
LINK_PATTERN = re.compile(
    r"https?://\S+|discord(?:app)?\.com/invite/\S+|discord\.gg/\S+",
    re.IGNORECASE,
)


def emoji_count(content):
    return len(EMOJI_PATTERN.findall(content or ""))


def link_count(content):
    return len(LINK_PATTERN.findall(content or ""))


def calculate_message_heat(message, state, now, inactive_channel=False):
    """Score one message without Discord or database dependencies.

    The caller owns heat decay and enforcement. Keeping scoring pure makes the
    thresholds deterministic and easy to regression test.
    """
    content = (getattr(message, "content", "") or "").strip()
    lowered = content.casefold()
    heat = 7.0
    reasons = []

    interval = now - state.get("last_message_at", 0)
    if interval < 1.2:
        heat += 17
        reasons.append("rapid messages")
    elif interval < 2.5:
        heat += 8

    previous = state.get("last_content", "")
    if lowered and previous:
        similarity = difflib.SequenceMatcher(None, previous, lowered).ratio()
        if similarity >= 0.92:
            heat += 42
            reasons.append("repeated content")
        elif similarity >= 0.72:
            heat += 20
            reasons.append("similar content")

    mention_count = len(getattr(message, "mentions", [])) + len(
        getattr(message, "role_mentions", [])
    )
    if getattr(message, "mention_everyone", False):
        heat += 85
        reasons.append("public mention")
    if mention_count:
        heat += mention_count * 14
        reasons.append("mention spam")

    emojis = emoji_count(content)
    if emojis > 4:
        heat += min(45, (emojis - 4) * 6)
        reasons.append("emoji spam")

    if len(content) > 600:
        heat += min(45, (len(content) - 600) / 35)
        reasons.append("wall of text")
    newlines = content.count("\n")
    if newlines > 6:
        heat += min(35, (newlines - 6) * 4)
        reasons.append("line spam")

    media_count = sum(
        len(getattr(message, field, []))
        for field in ("attachments", "embeds", "stickers")
    )
    if media_count:
        heat += 15 + 8 * max(0, media_count - 1)
        reasons.append("attachment spam")

    links = link_count(content)
    if links:
        heat += 18 * links
        reasons.append("link spam")

    if inactive_channel and interval < 4:
        heat += 14
        reasons.append("inactive-channel flood")

    state["last_content"] = lowered[:2000]
    state["last_message_at"] = now
    return heat, reasons
