"""Shared visual theme for MidVox Discord responses."""

# Bright sage stays readable against Discord's dark interface and matches the
# dashboard's MidVox palette.
PRIMARY = 0xA8BD6D
PRIMARY_DARK = 0x667744
SUCCESS = 0x57F287
WARNING = 0xFEE75C
ERROR = 0xED4245
INFO = 0x5865F2
NEUTRAL = 0x2B2D31


def status_color(status: str) -> int:
    return {
        "success": SUCCESS,
        "warning": WARNING,
        "error": ERROR,
        "info": INFO,
    }.get(status.lower(), PRIMARY)
