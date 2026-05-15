# Movie Bot — Codebase Map

## Overview

A Telegram bot that lets authorised users search for and download movies and TV shows via The Pirate Bay, managed by qBittorrent. After download completes, Jellyfin library is refreshed and subtitles are fetched automatically from OpenSubtitles.

Runs in Docker alongside a Cloudflare tunnel container (`docker-compose.yml`). qBittorrent also runs in Docker, sharing the network namespace of a `gluetun` (NordVPN WireGuard) container so all torrent traffic is VPN-routed. The bot stays on host networking and reaches qBittorrent at `127.0.0.1:8080` (published by gluetun, host-only). See `VPN_SETUP.md` for one-time setup.

---

## File Structure

```
movie-bot/
├── bot.py                  # Entry point — wires all handlers, starts polling
├── config.py               # Reads all env vars from .env
├── search.py               # TPB API queries, torrent filtering and ranking
├── qbit.py                 # qBittorrent API wrapper
├── jellyfin.py             # Jellyfin library refresh + duplicate detection
├── subtitles.py            # OpenSubtitles download (English + Croatian)
├── tmdb.py                 # TMDB API — Top Rated / Popular / Now Playing lists
├── hdr_convert.py          # HDR format detection and conversion (DV→HDR10, HDR10+→HDR10)
├── handlers/
│   ├── common.py           # Shared constants (states, require_auth decorator)
│   ├── misc.py             # start, movies, tv, status, cancel, main menu, cmd callbacks
│   ├── tv.py               # TV season/episode selection and download flow
│   └── list_flow.py        # TMDB list browsing and torrent picking flow
└── data/
    ├── title_map.json      # Persisted title normalisation map
    └── user_map.json       # Persisted user ID map
```

---

## Core Files

### `bot.py`
- Runs in **webhook mode** only (listens on `127.0.0.1:8089`, URL path = bot token). `WEBHOOK_URL` must be set in `.env` or the bot will refuse to start. Webhook traffic is reverse-proxied through the existing Cloudflare Tunnel (`bot.movies-oshinsky.win` → `localhost:8089`).
- Builds the `ConversationHandler` with all states and entry points.
- Entry points: `/movies`, `/tv`, `/list` commands **and** `cmd_movies`, `cmd_tv`, `cmd_list` inline callbacks (so the main menu can restart a flow).
- Fallbacks also include `cmd_movies_cb`, `cmd_tv_cb`, `cmd_list_cb` — clicking these while mid-flow auto-cancels the current conversation and starts the new one.
- Global handlers outside the conversation: `/status`, `/jellyfin`, `cmd_status`, `cmd_jellyfin` callbacks, delete/confirm-delete callbacks.
- `poll_downloads()` runs every 30 s: detects newly completed torrents, triggers Jellyfin refresh and subtitle download.
- `_prefetch_season_episodes(show, season)` — async helper that calls `search_season_episodes` in a thread; returns `([], [])` on error. Used to pre-populate episode data while the user reads the season picker.
- `_do_search(context, chat_id, query, user_id)` — runs the TPB search and edits the interface message with results. Signature uses `(context, chat_id)` instead of a `message` object. For TV mode: after showing the season picker, fires one `asyncio.Task` per season (via `_prefetch_season_episodes`) for any season that has no cached episodes yet; stores them in `user_data["tv_prefetch_tasks"]`.
- `search()` — text message handler; deletes the user's message first (keeps chat clean), then calls `_do_search`.
- `pick()` handles the final torrent selection; edits interface to show confirmation + main menu on success, or returns to episode picker for TV single-episode mode.

### `config.py`
Reads from `.env`:
- `TELEGRAM_TOKEN`, `TELEGRAM_ALLOWED_USERS`
- `QB_HOST`, `QB_PORT`, `QB_DOWNLOAD_DIR`, `QB_TV_DIR`
- `JELLYFIN_URL`, `JELLYFIN_PUBLIC_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_MEDIA_BASE`
- `TMDB_API_KEY`
- `OPENSUBTITLES_USERNAME`, `OPENSUBTITLES_PASSWORD`, `OPENSUBTITLES_API_KEY`

### `search.py`
- Module-level `requests.Session` with `Retry(total=3, backoff_factor=0.5, status_forcelist=[429,500,502,503,504])` mounted on `https://`. All `_fetch()` calls reuse one TCP connection to apibay.org with auto-retry on transient failures.
- `_fetch(query, cat)` — single GET to apibay.org with a 5s timeout. Results are cached for 30s in a thread-safe dict keyed by `(query, cat)`.
- `_fetch_combined(query, cats)` — fetches all categories in parallel via `ThreadPoolExecutor`, deduplicates by `info_hash`. TV searches (4 categories) complete in ~1 round-trip instead of 4 sequential ones.
- `search_torrents(query, mode)` — fetches from TPB `/q.php`, prefers 1080p, returns top 5 by seeders.
- `search_tv_seasons(query)` — returns list of available season numbers from cached results.
- `get_season_pack_results()` — filters for season-pack torrents (season tag, no episode code).
- `get_episode_numbers()` / `get_episode_results()` — filters individual episodes from cached results.
- `search_season_episodes()` — fresh TPB search when episode cache is empty; short-circuits after first query that returns results.
- `build_magnet()` — constructs magnet URI with standard trackers.
- `format_size()` — formats bytes to MB/GB string.

### `qbit.py`
Thin async wrapper around `qbittorrentapi`. All public functions are `async` and offload the blocking HTTP call to a thread via `asyncio.to_thread` (sync bodies live in `_*_sync` helpers). Call sites must `await` them.
- `add_torrent(magnet, save_path, category)` — adds torrent with `seeding_time_limit=0`.
- `get_torrents()` — returns all Movies + TV torrents with progress and ETA.
- `get_torrent_states()` — returns `{hash: is_complete}` dict used by the poller.
- `torrent_exists(info_hash)` — deduplication check before adding.
- `delete_torrent(info_hash)` — removes torrent and files.
- `get_torrent_paths(hashes)` — returns `content_path` for completed torrents.

### `hdr_convert.py`
- `is_dolby_vision(path)` — detects DV via codec tag (`dvhe`/`dvh1`) or `DOVI` side data in ffprobe output.
- `is_hdr10plus(path)` — detects HDR10+ via `HDR Dynamic`/`SMPTE2094` side data in ffprobe output.
- `_convert(path, tool_args, label)` — shared pipeline: extract raw HEVC with ffmpeg → run conversion tool → remux back, replacing the original in-place. Cleans up temp files on success or failure.
- `maybe_convert(path)` — called by `poll_downloads()` after `_ensure_movie_in_folder`; no-op if neither DV nor HDR10+ is detected.
- Requires `ffmpeg`, `dovi_tool` (2.3.2), and `hdr10plus_tool` (1.7.2) in PATH (installed in Docker image).

### `jellyfin.py`
- Module-level `requests.Session` with retry adapter (`Retry(total=3, backoff_factor=0.5)`) mounted on `http://` for resilience against transient Jellyfin errors.
- `refresh_library()` — POST to Jellyfin `/Library/Refresh`.
- `find_shared_by_title(torrent_name, shared_dir)` — normalises and compares names to detect already-downloaded content.

### `subtitles.py`
- Uses **subliminal** with the OpenSubtitlesCom provider.
- Downloads English (`en`) and Croatian (`hr`) subtitles, up to 2 per language per file.
- `check_subtitles_available(title)` — called before movie search; if no subtitles found, user is warned. Pre-fetches and caches subtitle content so it can be written immediately on download completion.
- `fetch_subtitles(path)` — called by the download poller for each newly completed torrent.
- `fetch_subtitles_all()` — scans entire movie and TV directories (used by `/subtitles` command, still available but removed from main menu).
- Contains a monkey-patch for subliminal 2.6.0 to include `year` in queries and avoid pagination errors.

### `tmdb.py`
- Module-level `requests.Session` with retry adapter, installed as `tmdbsimple.REQUESTS_SESSION`. `Connection: close` is popped from `tmdb_base.TMDB.headers` so HTTP keep-alive works — `get_top_rated()`'s 13 sequential pages reuse a single TCP connection instead of opening 13.
- `get_top_rated()` — 13 pages (~250 movies).
- `get_popular()` — 5 pages.
- `get_now_playing()` — 1 page.
- All results cached in-memory for 1 hour (`_CACHE_TTL = 3600`).

---

## Handlers

### `handlers/common.py`
- Defines all ConversationHandler state integers: `SEARCHING`, `PICKING`, `TV_SEASON`, `TV_EPISODE`, `TV_ALL_PICKING`, `LIST_MENU`, `LIST_BROWSING`, `LIST_PICKING`, `SUBTITLE_CONFIRM`.
- `require_auth` decorator — checks `update.effective_user.id` against `ALLOWED_USERS`.
- `_safe_name(name)` — strips filesystem-unsafe characters for directory naming.

### `handlers/misc.py`
- `edit_interface(context, chat_id, text, markup, parse_mode)` — core helper: edits the single tracked interface message (`iface_{chat_id}` in `bot_data`) or sends a new one and tracks it. All bot output flows through this function to maintain a single message per chat.
- `_merge_keyboards(*markups)` — combines multiple `InlineKeyboardMarkup` objects by appending all rows.
- `send_main_menu(message, context, prefix)` — edits the interface message to show the main menu, optionally prepending a status prefix (e.g. "✓ Queued: ...").
- `_cancel_keyboard()` — single ❌ Cancel button, shown when bot prompts for a search title.
- `_show_torrent_list(context, chat_id, page, full_results, header)` — slices `full_results` by `_PAGE_SIZE = 5` and edits the interface to show that page's pick buttons, page nav (◀️ Previous / Next ▶️ when applicable), and resolution-switch buttons (read from `_all_res_groups` + `_current_res` in user_data). Stores `results` (page slice), `_full_results`, and `_page` in user_data.
- `show_with_preference(context, chat_id, results, post_state, header, user_id)` — applies resolution preference filtering then calls `_show_torrent_list` with the full sorted list (page 0); returns the next conversation state. Movies always use 1080p, TV uses user preference. Sets `_current_res` in user_data for preferred/switched paths; clears it for `any` and fallback paths.
- `page_nav_cb` — handles `page_next`/`page_prev` callbacks; reads `_full_results` and `_page` from user_data, clamps, and re-renders via `_show_torrent_list`. Registered in PICKING and LIST_PICKING states in `bot.py`.
- `start` — sends full help text listing all commands (uses `reply_text`, not tracked).
- `movies` / `tv` — set `mode` in `user_data`, edit interface to prompt for title, return `SEARCHING`.
- `status` — edits interface to show active downloads + delete buttons + main menu buttons combined.
- `cancel` — ends conversation, edits interface to show main menu.
- `retry_search` — edits interface to re-prompt for title with cancel button, returns `SEARCHING`.
- `cmd_movies_cb` / `cmd_tv_cb` — inline button equivalents of `/movies` and `/tv`; sets `iface_` to the clicked message then calls `edit_interface`.
- `cmd_status_cb` — edits interface to show status + delete buttons + main menu buttons in one message.
- `cmd_jellyfin_cb` — edits interface to show Jellyfin URL + refresh button + main menu buttons.
- `cmd_preferences_cb` — edits interface to show resolution preference picker + main menu buttons.
- `jellyfin_refresh_cb` — edits interface to "⏳ Refreshing...", then to result + main menu.
- Delete flow: `delete_torrent_cb` → edits interface to delete confirmation → `confirm_delete_cb` / `cancel_delete_cb` → edits interface to main menu.

### `handlers/tv.py`
- `season_pick` — user picks a season. Checks `user_data["tv_prefetch_tasks"]` for a pre-running background task for that season; awaits it (showing "⏳ Loading…" only if it's still in flight). Falls back to an inline `search_season_episodes` call only if no prefetch task exists. Then falls back to season packs if no individual episodes are found. All output via `edit_interface`.
- `_render_episode_picker(context, chat_id, show, season, episodes)` — edits interface to episode grid buttons (6 per row) plus All Episodes / Back / Cancel.
- `browse_episodes_cb` — shows episode picker after "Individual Episodes" button.
- `back_to_seasons` — edits interface to re-render the season picker.
- `episode_pick` — fetches episode-specific results, shows torrent list via `show_with_preference`, returns `PICKING`.
- `season_pack_pick` — fetches season pack results, sets `is_season_pack=True`, returns `PICKING`.
- `all_episodes_start` / `all_episode_pick` / `_show_next_all_episode(context, chat_id)` — sequential episode-by-episode download queue; edits interface to main menu when queue is empty. Errors in `all_episode_pick` are silently skipped to keep the queue moving.

### `handlers/list_flow.py`
- `list_movies` / `cmd_list_cb` — show list type selector (Top Rated, Popular, Now Playing).
- `list_type_pick` — fetches from TMDB, renders paginated movie list.
- `list_page` — navigates pages.
- `list_pick_movie` — checks subtitle availability then searches TPB for the selected movie.

---

## Conversation Flow

```
/movies or /tv
    └─> SEARCHING (user types title)
            └─> movies: PICKING (pick torrent) ──> ConversationHandler.END + main menu
            └─> tv: TV_SEASON (pick season)
                    └─> TV_EPISODE (pick episode / season pack / all)
                            └─> PICKING (single episode torrent) ──> TV_EPISODE (loop)
                            └─> TV_ALL_PICKING (sequential queue) ──> END + main menu
                            └─> season_pack: PICKING ──> END + main menu

/list
    └─> LIST_MENU (pick list type)
            └─> LIST_BROWSING (paginated movie list)
                    └─> LIST_PICKING (pick torrent) ──> END + main menu

❌ Cancel (any state) ──> END + main menu
```

---

## Download → Post-processing Pipeline

1. Torrent added to qBittorrent via magnet URI.
2. `poll_downloads()` runs every 30 s, detects state change to complete.
3. Jellyfin library refresh triggered.
4. For movies: file moved into a named subfolder if it landed bare in the download dir.
5. `maybe_convert(path)` called — if DV or HDR10+ detected, converts to HDR10 in-place before subtitles.
6. `fetch_subtitles(path)` called — writes EN and HR `.srt` files alongside the video.
6. Season packs are excluded from subtitle fetching (tracked via `season_pack_hashes` in `bot_data`).

---

## Environment Variables (`.env`)

| Variable | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | Bot token from BotFather |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs |
| `QB_HOST` / `QB_PORT` | qBittorrent WebUI address |
| `QB_DOWNLOAD_DIR` | Movies save path |
| `QB_TV_DIR` | TV shows save path |
| `JELLYFIN_URL` | Internal Jellyfin URL |
| `JELLYFIN_PUBLIC_URL` | Public-facing Jellyfin URL shown to users |
| `JELLYFIN_API_KEY` | Jellyfin API key |
| `JELLYFIN_MEDIA_BASE` | Base path for shared media (duplicate detection) |
| `TMDB_API_KEY` | TMDB v3 API key |
| `OPENSUBTITLES_USERNAME` / `_PASSWORD` / `_API_KEY` | OpenSubtitles.com credentials |
| `WEBHOOK_URL` | Public HTTPS URL for Telegram webhook (e.g. `https://bot.movies-oshinsky.win`). Required — bot exits if unset. |
| `NORDVPN_WG_PRIVATE_KEY` | NordVPN WireGuard private key, consumed by the `gluetun` container. See `VPN_SETUP.md` for how to obtain. |
| `NORDVPN_COUNTRIES` | Optional, comma-separated country list for gluetun server selection (default: `Switzerland`). |
| `TZ` | Optional timezone passed to `gluetun` and `qbittorrent` containers (default: `Europe/Ljubljana`). |
