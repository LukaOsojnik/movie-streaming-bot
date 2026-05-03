import logging
import os
import time
from config import (
    QB_DOWNLOAD_DIR, QB_TV_DIR,
    OPENSUBTITLES_USERNAME, OPENSUBTITLES_PASSWORD, OPENSUBTITLES_API_KEY,
)
from subliminal import scan_videos, region
from subliminal.core import ProviderPool
from subliminal.providers.opensubtitlescom import OpenSubtitlesComProvider
from subliminal.refiners.hash import hash_opensubtitles
from subliminal.video import Movie, Episode, Video
from babelfish import Language

region.configure('dogpile.cache.memory', {})

# subliminal 2.6.0 omits year from the query, causing 20+ page pagination and Bad Request errors.
# It also adds a bare {'query': title} fallback criterion that re-triggers the same problem.
_original_make_query = OpenSubtitlesComProvider._make_query


def _make_query_with_year(self, *, query=None, year=None, **kwargs):
    criteria = _original_make_query(self, query=query, year=year, **kwargs)
    if year and query:
        # Drop the bare query-only fallback that searches without year and hits page limits
        criteria = [c for c in criteria if c != {'query': query.replace("'", '')}]
    return criteria


def _list_subtitles_with_year(self, video, languages):
    query = season = episode = year = None
    if isinstance(video, Episode):
        query = video.series
        season = video.season
        episode = video.episode
        year = video.year
    elif isinstance(video, Movie):
        query = video.title
        year = video.year
    return self.query(
        languages,
        moviehash=video.hashes.get('opensubtitles'),
        imdb_id=video.imdb_id,
        query=query,
        year=year,
        season=season,
        episode=episode,
        allow_machine_translated=False,
        sort_by_download_count=True,
    )


OpenSubtitlesComProvider._make_query = _make_query_with_year
OpenSubtitlesComProvider.list_subtitles = _list_subtitles_with_year

_SUBTITLE_LANGUAGES = {Language('eng'), Language('hrv')}
_SUBTITLE_PROVIDER_CONFIGS = {
    'opensubtitlescom': {
        'username': OPENSUBTITLES_USERNAME,
        'password': OPENSUBTITLES_PASSWORD,
        'apikey': OPENSUBTITLES_API_KEY or None,
    }
}

_SUBTITLE_TOP_N = 2
_SUBTITLE_DELAY = 2  # seconds between videos to stay within OpenSubtitles rate limits

# title.lower() → {lang_alpha2: [content_bytes, ...]} pre-fetched during availability check
_subtitle_cache: dict[str, dict[str, list[bytes]]] = {}


def _add_hashes(videos: list) -> None:
    for video in videos:
        h = hash_opensubtitles(video.name)
        if h:
            video.hashes['opensubtitles'] = h


def _download_top_subtitles(videos: list) -> tuple[list[str], list[str]]:
    downloaded = []
    failed = []
    with ProviderPool(providers=['opensubtitlescom'], provider_configs=_SUBTITLE_PROVIDER_CONFIGS) as pool:
        for i, video in enumerate(videos):
            if i > 0:
                time.sleep(_SUBTITLE_DELAY)
            base = os.path.splitext(video.name)[0]
            video_langs = []
            video_errors = []
            for lang in _SUBTITLE_LANGUAGES:
                slot_paths = [
                    f"{base}.{lang.alpha2}.srt",
                    f"{base}.{lang.alpha2}.2.srt",
                ]
                missing_slots = [p for p in slot_paths if not os.path.exists(p)]
                if not missing_slots:
                    continue
                try:
                    candidates = pool.list_subtitles(video, {lang})
                except Exception as e:
                    logging.warning("Failed to list subtitles for %s [%s]: %s", video.name, lang, e)
                    video_errors.append(f"{lang.alpha2}: {e}")
                    continue
                saved = 0
                for sub, path in zip(candidates, missing_slots):
                    try:
                        pool.download_subtitle(sub)
                        if not sub.content:
                            continue
                        with open(path, 'wb') as f:
                            f.write(sub.content)
                        saved += 1
                    except Exception as e:
                        logging.warning("Failed to download subtitle for %s: %s", video.name, e)
                        video_errors.append(f"{lang.alpha2}: {e}")
                if saved:
                    video_langs.append(lang.alpha2)
            name = os.path.basename(video.name)
            if video_langs:
                downloaded.append(f"{name} [{', '.join(video_langs)}]")
            if video_errors:
                failed.append(f"{name} — {'; '.join(video_errors)}")
    return downloaded, failed


def fetch_subtitles(path: str) -> bool:
    if os.path.isfile(path):
        try:
            videos = [Video.fromname(path)]
        except Exception:
            return False
    else:
        videos = scan_videos(path)
    if not videos:
        return False

    any_saved = False
    need_api = []
    for video in videos:
        cached = None
        if isinstance(video, Movie) and video.title:
            cached = _subtitle_cache.pop(video.title.lower(), None)
        if cached:
            base = os.path.splitext(video.name)[0]
            for lang_alpha2, contents in cached.items():
                slot_paths = [
                    f"{base}.{lang_alpha2}.srt",
                    f"{base}.{lang_alpha2}.2.srt",
                ]
                missing = [p for p in slot_paths if not os.path.exists(p)]
                for content, slot_path in zip(contents, missing):
                    try:
                        with open(slot_path, 'wb') as f:
                            f.write(content)
                        any_saved = True
                    except Exception as e:
                        logging.warning("Failed to write cached subtitle to %s: %s", slot_path, e)
        else:
            need_api.append(video)

    if need_api:
        _add_hashes(need_api)
        downloaded, _ = _download_top_subtitles(need_api)
        if downloaded:
            any_saved = True

    return any_saved


def fetch_subtitles_all() -> tuple[list[str], list[str]]:
    videos = scan_videos(QB_DOWNLOAD_DIR) + scan_videos(QB_TV_DIR)
    if not videos:
        return [], []
    _add_hashes(videos)
    return _download_top_subtitles(videos)


def check_subtitles_available(title: str) -> bool:
    dummy = Movie(title, title=title)
    cfg = _SUBTITLE_PROVIDER_CONFIGS['opensubtitlescom']
    try:
        provider = OpenSubtitlesComProvider(
            username=cfg['username'],
            password=cfg['password'],
            apikey=cfg['apikey'],
        )
        found: dict[str, list[bytes]] = {}
        with provider:
            for lang in _SUBTITLE_LANGUAGES:
                candidates = provider.list_subtitles(dummy, {lang})
                if not candidates:
                    continue
                contents: list[bytes] = []
                for sub in candidates[:_SUBTITLE_TOP_N]:
                    provider.download_subtitle(sub)
                    if sub.content:
                        contents.append(sub.content)
                if contents:
                    found[lang.alpha2] = contents
        if found:
            _subtitle_cache[title.lower()] = found
        return bool(found)
    except Exception as e:
        logging.warning("Subtitle availability check failed for %r: %s", title, e)
        return True
