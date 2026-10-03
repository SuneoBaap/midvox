"""Choose the highest single-file video that fits a Discord upload."""

import os


def upload_budget(configured, guild_limit=None):
    return min(configured, int(guild_limit * 0.98)) if guild_limit else configured


def fitting_formats(info, limit):
    candidates = []
    for fmt in info.get("formats") or [info]:
        if not fmt.get("url") or fmt.get("vcodec") == "none" or fmt.get("acodec") == "none":
            continue
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        if not size and fmt.get("tbr") and info.get("duration"):
            size = fmt["tbr"] * 1000 * info["duration"] / 8
        if size and size > limit:
            continue
        candidates.append(fmt)
    return sorted(candidates, key=lambda f: (
        f.get("height") or 0, f.get("width") or 0,
        f.get("fps") or 0, f.get("tbr") or 0,
    ), reverse=True)


def download_fitting_video(ydl, url, limit):
    info = ydl.extract_info(url, download=False)
    for fmt in fitting_formats(info, limit):
        selected = dict(info, formats=[fmt])
        result = ydl.process_ie_result(selected, download=True)
        path = ydl.prepare_filename(result)
        if path and os.path.isfile(path):
            if 0 < os.path.getsize(path) <= limit:
                return path
            os.remove(path)
    return None
