from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "")

_raw_users = os.getenv("TELEGRAM_ALLOWED_USERS", "")
ALLOWED_USERS: list[int] = [
    int(u.strip()) for u in _raw_users.split(",") if u.strip()
]

QB_HOST = os.getenv("QB_HOST", "localhost")
QB_PORT = int(os.getenv("QB_PORT", "8080"))
QB_DOWNLOAD_DIR = os.getenv("QB_DOWNLOAD_DIR", "/movies")
QB_TV_DIR = os.getenv("QB_TV_DIR", "/tv-series")

JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://localhost:8096")
JELLYFIN_PUBLIC_URL = os.getenv("JELLYFIN_PUBLIC_URL", JELLYFIN_URL)
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "")
JELLYFIN_MEDIA_BASE = os.getenv("JELLYFIN_MEDIA_BASE", "")
JELLYFIN_SHARED_MOVIES = os.path.join(JELLYFIN_MEDIA_BASE, "shared", "movies")
JELLYFIN_SHARED_TV = os.path.join(JELLYFIN_MEDIA_BASE, "shared", "tv-series")

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

OPENSUBTITLES_USERNAME = os.getenv("OPENSUBTITLES_USERNAME", "")
OPENSUBTITLES_PASSWORD = os.getenv("OPENSUBTITLES_PASSWORD", "")
OPENSUBTITLES_API_KEY = os.getenv("OPENSUBTITLES_API_KEY", "")
