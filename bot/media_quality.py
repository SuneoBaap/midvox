"""Choose the highest single-file video that fits a Discord upload."""

import os
import shutil
import subprocess
import tempfile
import json
import math


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


def download_fitting_video(ydl, url, limit, *, compress=False):
    info = ydl.extract_info(url, download=False)
    for fmt in fitting_formats(info, limit):
        selected = dict(info, formats=[fmt])
        result = ydl.process_ie_result(selected, download=True)
        path = ydl.prepare_filename(result)
        if path and os.path.isfile(path):
            if 0 < os.path.getsize(path) <= limit:
                return path
            os.remove(path)
    if compress:
        # Instagram can expose one oversized rendition with no lower qualities.
        # Download only the smallest complete source, then encode it to budget.
        sources = fitting_formats(info, float("inf"))
        source_limit = min(80_000_000, max(32_000_000, limit * 8))
        sources = [f for f in sources if not (f.get("filesize") or f.get("filesize_approx"))
                   or (f.get("filesize") or f.get("filesize_approx")) <= source_limit]
        if sources:
            fmt = min(sources, key=lambda f: (
                f.get("filesize") or f.get("filesize_approx") or float("inf"),
                f.get("height") or float("inf"), f.get("tbr") or float("inf"),
            ))
            previous = ydl.params.get("max_filesize")
            try:
                ydl.params["max_filesize"] = source_limit
                result = ydl.process_ie_result(dict(info, formats=[fmt]), download=True)
                path = ydl.prepare_filename(result)
                if path and os.path.isfile(path):
                    try:
                        if 0 < os.path.getsize(path) <= limit:
                            return path
                        if os.path.getsize(path) <= source_limit:
                            return compress_to_budget(path, limit)
                        return None
                    finally:
                        if os.path.exists(path) and not 0 < os.path.getsize(path) <= limit:
                            os.remove(path)
            finally:
                if previous is None:
                    ydl.params.pop("max_filesize", None)
                else:
                    ydl.params["max_filesize"] = previous
    return None


def compress_to_budget(path, limit):
    """Encode one oversized Reel to a bounded H.264/AAC upload, off the event loop."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return None
    output = None
    try:
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", path,
        ], capture_output=True, check=True, timeout=15)
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            return None
        # Reserve space for the MP4 container and bitrate variation.
        total_bitrate = int(limit * 0.90 * 8 / duration)
        audio_bitrate = min(96_000, int(total_bitrate * 0.20))
        video_bitrate = total_bitrate - audio_bitrate
        if audio_bitrate < 24_000 or video_bitrate < 64_000:
            return None
        handle, output = tempfile.mkstemp(prefix="instadl_discord_", suffix=".mp4")
        os.close(handle)
        with tempfile.TemporaryDirectory(prefix="instadl_encode_") as work:
            common = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                      "-i", path, "-map", "0:v:0", "-vf", r"scale=trunc(min(720\,iw)/2)*2:-2,fps=30",
                      "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                      "-b:v", str(video_bitrate), "-threads", "2", "-passlogfile", os.path.join(work, "pass")]
            subprocess.run(common + ["-pass", "1", "-an", "-f", "null", os.devnull],
                           capture_output=True, check=True, timeout=90)
            subprocess.run(common + ["-pass", "2", "-map", "0:a:0?", "-c:a", "aac",
                           "-b:a", str(audio_bitrate), "-movflags", "+faststart", output],
                           capture_output=True, check=True, timeout=90)
        if 0 < os.path.getsize(output) <= limit:
            result, output = output, None
            return result
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("[InstaDL] Reel compression could not produce a file within the upload budget")
    finally:
        if output and os.path.exists(output):
            os.remove(output)
    return None
