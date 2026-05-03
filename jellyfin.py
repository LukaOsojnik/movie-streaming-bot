import os
import re
import requests
from config import JELLYFIN_URL, JELLYFIN_API_KEY

_NOISE = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|bluray|blu.ray|bdrip|brrip|web.dl|webrip|"
    r"webdl|hdrip|hdtv|dvdrip|dvdscr|x264|x265|h264|h265|hevc|avc|xvid|divx|"
    r"aac|ac3|dts|truehd|atmos|10bit|hdr|dv|dolby|proper|repack|extended|"
    r"theatrical|unrated|yify|yts|rarbg|\d{4})\b",
    re.IGNORECASE,
)


def _normalize_title(name: str) -> str:
    name = re.sub(r"[._\-]", " ", name)
    name = re.sub(r"\[.*?\]|\(.*?\)", " ", name)
    name = _NOISE.sub("", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def find_shared_by_title(torrent_name: str, shared_dir: str) -> str | None:
    key = _normalize_title(torrent_name)
    if not key or not os.path.isdir(shared_dir):
        return None
    for entry in os.scandir(shared_dir):
        if _normalize_title(entry.name) == key:
            return entry.path
    return None


def _headers() -> dict:
    return {"X-Emby-Token": JELLYFIN_API_KEY, "Content-Type": "application/json"}


def refresh_library() -> None:
    requests.post(
        f"{JELLYFIN_URL}/Library/Refresh",
        headers={"X-Emby-Token": JELLYFIN_API_KEY},
        timeout=10,
    )
