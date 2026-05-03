import time
import tmdbsimple as tmdb_lib
from config import TMDB_API_KEY

tmdb_lib.API_KEY = TMDB_API_KEY
tmdb_lib.REQUESTS_TIMEOUT = 10

_CACHE: dict = {}
_CACHE_TTL = 3600


def _cached(key: str, fetch_fn) -> list[dict]:
    now = time.monotonic()
    if key in _CACHE and (now - _CACHE[key]["fetched_at"]) < _CACHE_TTL:
        return _CACHE[key]["data"]
    try:
        data = fetch_fn()
    except Exception as e:
        raise ConnectionError(f"⚠️ Cannot reach TMDB: {e}") from e
    _CACHE[key] = {"data": data, "fetched_at": now}
    return data


def _normalize(results: list[dict]) -> list[dict]:
    out = []
    for m in results:
        year = m.get("release_date", "")[:4]
        out.append({
            "title": m.get("title", "Unknown"),
            "year": int(year) if year.isdigit() else 0,
            "rating": round(m.get("vote_average", 0.0), 1),
            "tmdb_id": m.get("id", 0),
        })
    return out


def get_top_rated(pages: int = 13) -> list[dict]:
    def fetch():
        movies_api = tmdb_lib.Movies()
        results = []
        for page in range(1, pages + 1):
            movies_api.top_rated(page=page, language="en-US")
            results.extend(movies_api.results)
        return _normalize(results)
    return _cached("top_rated", fetch)


def get_popular() -> list[dict]:
    def fetch():
        movies_api = tmdb_lib.Movies()
        results = []
        for page in range(1, 6):
            movies_api.popular(page=page, language="en-US")
            results.extend(movies_api.results)
        return _normalize(results)
    return _cached("popular", fetch)


def get_now_playing() -> list[dict]:
    def fetch():
        movies_api = tmdb_lib.Movies()
        movies_api.now_playing(language="en-US")
        return _normalize(movies_api.results)
    return _cached("now_playing", fetch)
