import qbittorrentapi
from config import QB_HOST, QB_PORT, QB_DOWNLOAD_DIR

COMPLETE_STATES = {"uploading", "stalledUP", "pausedUP", "checkingUP", "forcedUP", "queuedUP"}

STATE_ICONS = {
    "downloading": "⬇️",
    "uploading": "⬆️",
    "stalledDL": "⏸ stalled",
    "stalledUP": "⏸ stalled",
    "pausedDL": "⏸ paused",
    "pausedUP": "⏸ paused",
    "queuedDL": "🕐 queued",
    "queuedUP": "🕐 queued",
    "checkingDL": "🔍 checking",
    "checkingUP": "🔍 checking",
    "moving": "📦 moving",
    "error": "❌ error",
    "missingFiles": "❌ missing files",
}


def get_torrents() -> list[dict]:
    try:
        qbt = qbittorrentapi.Client(host=QB_HOST, port=QB_PORT)
        torrents = list(qbt.torrents_info(category="Movies")) + list(qbt.torrents_info(category="TV"))
        result = []
        for t in torrents:
            state = STATE_ICONS.get(t.state, t.state)
            if t.state in COMPLETE_STATES or t.progress >= 1.0:
                progress = "Done"
            else:
                progress = f"{t.progress * 100:.1f}%"
            result.append({
                "name": t.name,
                "state": state,
                "progress": progress,
                "eta": t.eta,
            })
        return result
    except qbittorrentapi.exceptions.APIConnectionError as e:
        raise ConnectionError("⚠️ Cannot reach qBittorrent") from e


def get_torrent_states() -> dict[str, bool]:
    try:
        qbt = qbittorrentapi.Client(host=QB_HOST, port=QB_PORT)
        torrents = list(qbt.torrents_info(category="Movies")) + list(qbt.torrents_info(category="TV"))
        return {t.hash: (t.state in COMPLETE_STATES or t.progress >= 1.0) for t in torrents}
    except qbittorrentapi.exceptions.APIConnectionError:
        return {}


def torrent_exists(info_hash: str) -> bool:
    try:
        qbt = qbittorrentapi.Client(host=QB_HOST, port=QB_PORT)
        return bool(qbt.torrents_info(hashes=info_hash))
    except qbittorrentapi.exceptions.APIConnectionError:
        return False


def get_torrent_paths(hashes: set[str]) -> dict[str, str]:
    try:
        qbt = qbittorrentapi.Client(host=QB_HOST, port=QB_PORT)
        torrents = list(qbt.torrents_info(category="Movies")) + list(qbt.torrents_info(category="TV"))
        return {t.hash: t.content_path for t in torrents if t.hash in hashes and t.content_path}
    except qbittorrentapi.exceptions.APIConnectionError:
        return {}


def add_torrent(magnet: str, save_path: str = QB_DOWNLOAD_DIR, category: str = "Movies") -> None:
    try:
        qbt = qbittorrentapi.Client(host=QB_HOST, port=QB_PORT)
        result = qbt.torrents_add(
            urls=magnet,
            save_path=save_path,
            category=category,
            seeding_time_limit=0,
        )
    except qbittorrentapi.exceptions.APIConnectionError as e:
        raise ConnectionError("⚠️ Cannot reach qBittorrent") from e

    if result != "Ok.":
        raise RuntimeError(result)
