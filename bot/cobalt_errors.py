"""Preserve actionable extraction failures instead of suggesting blind retries."""


class CobaltDownloadError(Exception):
    def __init__(self, code, user_message):
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def extraction_error(codes):
    if codes and all(code == "error.api.fetch.fail" for code in codes):
        return CobaltDownloadError(
            "error.api.fetch.fail",
            "YouTube blocked Cobalt's Railway/WARP connection for this Short. "
            "Cookie-free downloads cannot complete from the current server "
            "network; the bot owner must provide a fresh YouTube session or "
            "residential egress.",
        )
    if "error.api.youtube.login" in codes:
        return CobaltDownloadError(
            "error.api.youtube.login",
            "YouTube is asking the bot to sign in. The owner can connect its "
            "YouTube session at /dashboard/youtube-login. "
            "If you repost this link after a failed download, it will stay visible.",
        )
    if codes and all(code == "error.api.content.video.unavailable" for code in codes):
        return CobaltDownloadError(
            "error.api.content.video.unavailable",
            "YouTube reports this video unavailable. It may be private, removed, "
            "or restricted for the bot's connection.",
        )
    return None
