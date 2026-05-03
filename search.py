import re
import requests
from urllib.parse import quote

_SEASON_RE = re.compile(r'\bS(\d{1,2})(?:E\d+)?\b|\bSeason[. ]?(\d{1,2})\b', re.IGNORECASE)
_EPISODE_RE = re.compile(r'\bS\d{1,2}E(\d{2,3})\b', re.IGNORECASE)


def _show_pattern(show: str) -> re.Pattern:
    parts = re.escape(show).split(r'\ ')
    return re.compile(r'^' + r'[. _]'.join(parts), re.IGNORECASE)


def _filter_by_show(results: list[dict], show: str) -> list[dict]:
    pattern = _show_pattern(show)
    return [r for r in results if pattern.match(r["name"])]

TRACKERS = (
    "tr=udp://tracker.opentrackr.org:1337/announce"
    "&tr=udp://open.tracker.cl:1337/announce"
    "&tr=udp://tracker.openbittorrent.com:6969/announce"
)


def _fetch(query: str, cat: str) -> list[dict]:
    url = f"https://apibay.org/q.php?q={quote(query)}&cat={cat}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if len(data) == 1 and data[0].get("name") == "No results returned":
        return []
    return data


def _prefer_1080p(results: list[dict]) -> list[dict]:
    hd = [r for r in results if "1080p" in r["name"]]
    return hd if hd else results


def search_torrents(query: str, mode: str = "movies") -> list[dict]:
    cats = ["207", "200"] if mode == "movies" else ["208", "205", "200"]
    try:
        results = []
        for cat in cats:
            results = _fetch(query, cat)
            if results:
                break
    except requests.exceptions.RequestException as e:
        raise ConnectionError("⚠️ TPB is unreachable, try again later") from e

    results = _prefer_1080p(results)
    results.sort(key=lambda r: int(r["seeders"]), reverse=True)
    return results[:5]


def search_tv_seasons(query: str) -> tuple[list[int], list[dict]]:
    try:
        results = _fetch(query, "208")
        if not results:
            results = _fetch(query, "205")
    except requests.exceptions.RequestException as e:
        raise ConnectionError("⚠️ TPB is unreachable, try again later") from e

    results = _filter_by_show(results, query)
    seasons = set()
    for r in results:
        for m in _SEASON_RE.finditer(r["name"]):
            seasons.add(int(m.group(1) or m.group(2)))
    return sorted(seasons), results


def _filter_season(results: list[dict], season: int) -> list[dict]:
    return [
        r for r in results
        if any(
            int(m.group(1) or m.group(2)) == season
            for m in _SEASON_RE.finditer(r["name"])
        )
    ]


def get_season_results(show: str, season: int, cached_results: list[dict]) -> list[dict]:
    matched = _filter_season(cached_results, season)

    hd = [r for r in matched if "1080p" in r["name"]]
    if hd:
        hd.sort(key=lambda r: int(r["seeders"]), reverse=True)
        return hd[:5]

    dot_query = f"{show.replace(' ', '.')}.S{season:02d}"
    try:
        dot_results = []
        for cat in ["208", "205", "200"]:
            dot_results = _fetch(dot_query, cat)
            if dot_results:
                break
        dot_matched = _filter_season(_filter_by_show(dot_results, show), season)
        hd = [r for r in dot_matched if "1080p" in r["name"]]
        if hd:
            hd.sort(key=lambda r: int(r["seeders"]), reverse=True)
            return hd[:5]
        if dot_matched:
            dot_matched.sort(key=lambda r: int(r["seeders"]), reverse=True)
            return dot_matched[:5]
    except requests.exceptions.RequestException:
        pass

    matched.sort(key=lambda r: int(r["seeders"]), reverse=True)
    return matched[:5]


def get_episode_numbers(results: list[dict], season: int) -> list[int]:
    season_results = _filter_season(results, season)
    episodes = set()
    for r in season_results:
        for m in _EPISODE_RE.finditer(r["name"]):
            episodes.add(int(m.group(1)))
    return sorted(episodes)


def get_episode_results(show: str, season: int, episode: int, cached_results: list[dict]) -> list[dict]:
    def _filter_ep(results: list[dict]) -> list[dict]:
        pattern = re.compile(rf'\bS{season:02d}E{episode:02d}\b', re.IGNORECASE)
        return [r for r in results if pattern.search(r["name"])]

    matched = _filter_ep(_filter_season(cached_results, season))

    hd = [r for r in matched if "1080p" in r["name"]]
    if hd:
        hd.sort(key=lambda r: int(r["seeders"]), reverse=True)
        return hd[:5]

    dot_query = f"{show.replace(' ', '.')}.S{season:02d}E{episode:02d}"
    try:
        dot_results = []
        for cat in ["208", "205", "200"]:
            dot_results = _fetch(dot_query, cat)
            if dot_results:
                break
        dot_matched = _filter_ep(_filter_by_show(dot_results, show))
        hd = [r for r in dot_matched if "1080p" in r["name"]]
        if hd:
            hd.sort(key=lambda r: int(r["seeders"]), reverse=True)
            return hd[:5]
        if dot_matched:
            dot_matched.sort(key=lambda r: int(r["seeders"]), reverse=True)
            return dot_matched[:5]
    except requests.exceptions.RequestException:
        pass

    matched.sort(key=lambda r: int(r["seeders"]), reverse=True)
    return matched[:5]


def build_magnet(info_hash: str, name: str) -> str:
    return f"magnet:?xt=urn:btih:{info_hash}&dn={quote(name)}&{TRACKERS}"


def format_size(size_bytes: int) -> str:
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = size_bytes / (1024 ** 2)
    return f"{mb:.0f} MB"
