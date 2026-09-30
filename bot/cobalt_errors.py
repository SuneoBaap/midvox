"""Preserve actionable extraction failures instead of suggesting blind retries."""


class CobaltDownloadError(Exception):
    def __init__(self, code, user_message):
        super().__init__(code)
        self.code = code
        self.user_message = user_message


def extraction_error(codes):
    if "error.api.youtube.login" in codes:
        return CobaltDownloadError(
            "error.api.youtube.login",
            "YouTube is requiring sign-in for this Short. The bot owner needs "
            "to check its YouTube login session and download connection; "
            "retrying the link alone won't fix this.",
        )
    if codes and all(code == "error.api.content.video.unavailable" for code in codes):
        return CobaltDownloadError(
            "error.api.content.video.unavailable",
            "YouTube reports this video unavailable. It may be private, removed, "
            "or restricted for the bot's connection.",
        )
    return None
