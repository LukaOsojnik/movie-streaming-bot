# Movies / TV-series download bot

Got a movie recommendation? Just open Telegram, type the title into the bot, and it will remotely download it to your PC — with subtitles — and make it instantly available in your [Jellyfin](https://jellyfin.org/) library. No browsing torrent sites, no manual file management.

Pair this with a [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/) and you have your own private streaming platform accessible from anywhere in the world — no VPN, no port forwarding, no Tailscale. Point a domain at it and your friends can watch too, from any device, just like Netflix.

## Features

- Search and download movies and TV shows from The Pirate Bay
- Browse TMDB lists (Top Rated, Popular, Now Playing) and download directly
- TV show support: pick season, individual episodes, or all episodes at once
- Automatic subtitle downloads (English + Croatian) via OpenSubtitles
- Auto-refreshes Jellyfin library when a download completes — the movie shows up immediately
- Duplicate detection before adding torrents
- Works from anywhere — your phone, another computer, wherever Telegram is
- Stream your library from any device via Jellyfin exposed through a Cloudflare Tunnel — no VPN needed
- Share with friends via a custom domain (e.g. `movies.yourdomain.com`)

## Prerequisites

**Both platforms:**
- A running [qBittorrent](https://www.qbittorrent.org/) instance with:
  - Web UI enabled (Tools → Options → Web UI)
  - "Bypass authentication for clients on localhost" checked (or authentication fully disabled)
  - Two categories created: **Movies** and **TV** (Add Category in the sidebar)
- A running [Jellyfin](https://jellyfin.org/) instance with Movies and TV Shows libraries pointing at the same directories qBittorrent downloads to (see path setup in step 2)
- A Telegram bot token — create one via [@BotFather](https://t.me/BotFather)
- [TMDB API key](https://www.themoviedb.org/settings/api) (free)
- [OpenSubtitles.com](https://www.opensubtitles.com/) account and API key (free tier available)

**Linux (Docker):**
- [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/)

**Windows (Python directly):**
- [Python 3.11+](https://www.python.org/downloads/) — during install, check **"Add Python to PATH"**

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/movie-bot.git
cd movie-bot
```

### 2. Create the environment file

**Linux:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Edit `.env` with your values:

**Linux:**
```env
# Telegram
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_USERS=123456789,987654321

# qBittorrent — these paths must point to the same directories Jellyfin reads from
QB_HOST=localhost
QB_PORT=8080
QB_DOWNLOAD_DIR=/home/youruser/jellyfin-media/shared/movies
QB_TV_DIR=/home/youruser/jellyfin-media/shared/tv-series

# Jellyfin
# Used for internal API calls (library refresh, etc.)
JELLYFIN_URL=http://localhost:8096
# Shown to users by the /jellyfin command. Set to your public domain if using Cloudflare Tunnel.
# If omitted, defaults to JELLYFIN_URL.
JELLYFIN_PUBLIC_URL=https://movies.yourdomain.com
JELLYFIN_API_KEY=your_jellyfin_api_key
# Root of your media library. The bot expects shared/movies/ and shared/tv-series/ under it.
# QB_DOWNLOAD_DIR and QB_TV_DIR above must point to those same subdirectories.
JELLYFIN_MEDIA_BASE=/home/youruser/jellyfin-media
# Only required if using the cloudflared service
CLOUDFLARED_CONFIG_DIR=/home/youruser/.cloudflared

# TMDB
TMDB_API_KEY=your_tmdb_api_key

# OpenSubtitles
OPENSUBTITLES_USERNAME=your_username
OPENSUBTITLES_PASSWORD=your_password
OPENSUBTITLES_API_KEY=your_api_key
```

**Windows:** use `localhost` as normal, but paths must use Windows format:
```env
# Telegram
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_USERS=123456789,987654321

# qBittorrent — these paths must point to the same directories Jellyfin reads from
QB_HOST=localhost
QB_PORT=8080
QB_DOWNLOAD_DIR=C:/Users/youruser/jellyfin-media/shared/movies
QB_TV_DIR=C:/Users/youruser/jellyfin-media/shared/tv-series

# Jellyfin
# Used for internal API calls (library refresh, etc.)
JELLYFIN_URL=http://localhost:8096
# Shown to users by the /jellyfin command. Set to your public domain if using Cloudflare Tunnel.
# If omitted, defaults to JELLYFIN_URL.
JELLYFIN_PUBLIC_URL=https://movies.yourdomain.com
JELLYFIN_API_KEY=your_jellyfin_api_key
# Root of your media library. The bot expects shared/movies/ and shared/tv-series/ under it.
# QB_DOWNLOAD_DIR and QB_TV_DIR above must point to those same subdirectories.
JELLYFIN_MEDIA_BASE=C:/Users/youruser/jellyfin-media

# TMDB
TMDB_API_KEY=your_tmdb_api_key

# OpenSubtitles
OPENSUBTITLES_USERNAME=your_username
OPENSUBTITLES_PASSWORD=your_password
OPENSUBTITLES_API_KEY=your_api_key
```

**Finding your Telegram user ID:** message [@userinfobot](https://t.me/userinfobot) on Telegram.

**Finding your Jellyfin API key:** Jellyfin Dashboard → API Keys → New API key.

### 3. Install and run

**Linux** — build and start with Docker:
```bash
docker compose up -d
```

Check logs:
```bash
docker compose logs -f movie-bot
```

The `:z` on the volume mounts in `docker-compose.yml` is a SELinux relabelling option required on SELinux-enabled distributions (Fedora, RHEL, CentOS). Drop it if your system does not use SELinux.

**Windows** — install dependencies and run directly with Python:
```powershell
pip install -r requirements.txt
python bot.py
```

To keep it running in the background, you can use [NSSM](https://nssm.cc/) to register it as a Windows service, or simply leave a PowerShell window open.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show help |
| `/movies` | Search for a movie by title |
| `/tv` | Search for a TV show by title |
| `/list` | Browse TMDB lists (Top Rated, Popular, Now Playing) |
| `/status` | Show active downloads with progress and ETA |
| `/jellyfin` | Show the Jellyfin server address |
| `/subtitles` | Download missing subtitles for all library items |

## Notes

- Subtitles are downloaded automatically when a torrent completes. The bot will notify allowed users when subtitles are saved.
- The optional `cloudflared` service in `docker-compose.yml` exposes Jellyfin externally via a Cloudflare Tunnel — Linux only, remove it if you don't need it.
