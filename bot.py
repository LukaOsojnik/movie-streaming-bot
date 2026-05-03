import asyncio
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from config import TOKEN, QB_DOWNLOAD_DIR, QB_TV_DIR, ALLOWED_USERS
from search import search_torrents, search_tv_seasons, build_magnet, format_size
from qbit import add_torrent, torrent_exists, get_torrent_states, get_torrent_paths
from jellyfin import refresh_library, find_shared_by_title
from subtitles import fetch_subtitles, check_subtitles_available
from handlers.common import (
    SEARCHING, PICKING, TV_SEASON, TV_EPISODE, TV_ALL_PICKING,
    LIST_MENU, LIST_BROWSING, LIST_PICKING, SUBTITLE_CONFIRM,
    require_auth, _safe_name,
)
from handlers.misc import start, movies, tv, status, jellyfin_info, subtitles_all, cancel, delete_torrent_cb, confirm_delete_cb, cancel_delete_cb
from handlers.tv import season_pick, back_to_seasons, browse_episodes_cb, episode_pick, all_episodes_start, all_episode_pick, season_pack_pick
from handlers.list_flow import list_movies, list_type_pick, list_page, list_pick_movie

logging.basicConfig(level=logging.INFO)


async def _do_search(message, context: ContextTypes.DEFAULT_TYPE, query: str):
    mode = context.user_data.get("mode", "movies")

    if mode == "tv":
        await message.reply_text("🔍 Searching for seasons...")
        try:
            seasons, tv_results = search_tv_seasons(query)
        except ConnectionError as e:
            await message.reply_text(str(e))
            return SEARCHING

        if not seasons:
            await message.reply_text(f"❌ No results found for '{query}'")
            return SEARCHING

        context.user_data["tv_query"] = query
        context.user_data["tv_results"] = tv_results
        context.user_data["tv_seasons"] = seasons
        rows = [
            [InlineKeyboardButton(f"Season {s}", callback_data=f"season_{s}") for s in seasons[i:i+4]]
            for i in range(0, len(seasons), 4)
        ]
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        await message.reply_text(
            f'📺 Found seasons for "{query}". Pick one:',
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return TV_SEASON

    await message.reply_text("🔍 Searching...")
    try:
        results = search_torrents(query, mode)
    except ConnectionError as e:
        await message.reply_text(str(e))
        return SEARCHING

    if not results:
        await message.reply_text(f"❌ No results found for '{query}'")
        return SEARCHING

    context.user_data["results"] = results
    context.user_data["query"] = query

    lines = [f'🎬 Results for "{query}":\n']
    for i, r in enumerate(results, start=1):
        size = format_size(int(r["size"]))
        seeders = int(r["seeders"])
        lines.append(f"{i}. {r['name']}\n   🌱 {seeders} seeders · {size}")

    keyboard = [
        [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    return PICKING


@require_auth
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["pending_query"] = query

    mode = context.user_data.get("mode", "movies")

    if mode == "tv":
        return await _do_search(update.message, context, query)

    loop = asyncio.get_running_loop()
    available = await loop.run_in_executor(None, check_subtitles_available, query)

    if available:
        return await _do_search(update.message, context, query)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, continue", callback_data="subtitle_yes"),
            InlineKeyboardButton("❌ No, cancel", callback_data="subtitle_no"),
        ]
    ])
    await update.message.reply_text(
        f"⚠️ No subtitles found for '{query}'. Continue anyway?",
        reply_markup=keyboard,
    )
    return SUBTITLE_CONFIRM


@require_auth
async def subtitle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    if query_cb.data == "subtitle_no":
        await query_cb.message.reply_text("Cancelled.")
        return ConversationHandler.END

    query = context.user_data.get("pending_query", "")

    if context.user_data.pop("subtitle_origin", None) == "list":
        await query_cb.message.reply_text(f'🔍 Searching torrents for "{query}"...')
        try:
            results = search_torrents(query, "movies")
        except ConnectionError as e:
            await query_cb.message.reply_text(str(e))
            return LIST_BROWSING
        if not results:
            await query_cb.message.reply_text(f'❌ No torrents found for "{query}". Try another.')
            return LIST_BROWSING
        context.user_data["results"] = results
        lines = [f'🎬 Results for "{query}":\n']
        for i, r in enumerate(results, 1):
            size = format_size(int(r["size"]))
            lines.append(f"{i}. {r['name']}\n   🌱 {int(r['seeders'])} seeders · {size}")
        keyboard = [
            [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]
        await query_cb.message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        return LIST_PICKING

    return await _do_search(query_cb.message, context, query)


@require_auth
async def pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    idx = int(query_cb.data.split("_")[1])
    results = context.user_data.get("results", [])

    if idx >= len(results):
        await query_cb.message.reply_text("⚠️ Invalid selection.")
        return ConversationHandler.END

    r = results[idx]
    magnet = build_magnet(r["info_hash"], r["name"])
    info_hash = r["info_hash"]
    torrent_name = r["name"]

    mode = context.user_data.get("mode", "movies")

    if mode == "tv":
        show = _safe_name(context.user_data.get("tv_query", "Unknown"))
        season = context.user_data.get("tv_season", 1)
        scan_dir = f"{QB_TV_DIR}/{show}/Season {season:02d}"
        save_path = scan_dir
        category = "TV"
    else:
        scan_dir = QB_DOWNLOAD_DIR
        save_path = QB_DOWNLOAD_DIR
        category = "Movies"

    try:
        existing = find_shared_by_title(torrent_name, scan_dir)
        if existing:
            await query_cb.message.reply_text(f"✓ Already downloaded: {os.path.basename(existing)}")
        else:
            if not torrent_exists(info_hash):
                add_torrent(magnet, save_path=save_path, category=category)
            if context.user_data.pop("is_season_pack", False):
                context.application.bot_data.setdefault("season_pack_hashes", set()).add(info_hash)
            await query_cb.message.reply_text(f"✓ Added: {torrent_name}")
    except ConnectionError as e:
        await query_cb.message.reply_text(str(e))
    except RuntimeError as e:
        await query_cb.message.reply_text(f"✗ qBittorrent error: {e}")

    return ConversationHandler.END


def _ensure_movie_in_folder(path: str) -> str:
    if not os.path.isfile(path):
        return path
    if os.path.normpath(os.path.dirname(path)) != os.path.normpath(QB_DOWNLOAD_DIR):
        return path
    folder = os.path.join(QB_DOWNLOAD_DIR, os.path.splitext(os.path.basename(path))[0])
    os.makedirs(folder, exist_ok=True)
    new_path = os.path.join(folder, os.path.basename(path))
    os.rename(path, new_path)
    logging.info("Moved bare movie file into folder: %s", new_path)
    return new_path


async def poll_downloads(context: ContextTypes.DEFAULT_TYPE) -> None:
    states = get_torrent_states()  # {hash: is_complete}
    prev_incomplete: set = context.bot_data.get("prev_incomplete")

    if prev_incomplete is not None:
        now_complete = {h for h, done in states.items() if done}
        newly_done = prev_incomplete & now_complete
        if newly_done:
            try:
                refresh_library()
                logging.info("Jellyfin library refreshed for %d completed torrent(s)", len(newly_done))
            except Exception as e:
                logging.warning("Jellyfin refresh failed: %s", e)

            loop = asyncio.get_running_loop()
            season_pack_hashes = context.bot_data.get("season_pack_hashes", set())
            paths = get_torrent_paths(newly_done)
            for h, path in paths.items():
                if h in season_pack_hashes:
                    season_pack_hashes.discard(h)
                    continue
                try:
                    path = await loop.run_in_executor(None, _ensure_movie_in_folder, path)
                    saved = await loop.run_in_executor(None, fetch_subtitles, path)
                    if saved:
                        logging.info("Subtitles downloaded for %s", os.path.basename(path))
                except Exception as e:
                    logging.warning("Subtitle download failed for %s: %s", path, e)

    context.bot_data["prev_incomplete"] = {h for h, done in states.items() if not done}


def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("movies", movies),
            CommandHandler("tv", tv),
            CommandHandler("list", list_movies),
        ],
        states={
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, search)],
            SUBTITLE_CONFIRM: [
                CallbackQueryHandler(subtitle_confirm, pattern=r"^subtitle_(yes|no)$"),
            ],
            TV_SEASON: [
                CallbackQueryHandler(season_pick, pattern=r"^season_\d+$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            TV_EPISODE: [
                CallbackQueryHandler(episode_pick, pattern=r"^episode_\d+$"),
                CallbackQueryHandler(season_pack_pick, pattern=r"^season_pack$"),
                CallbackQueryHandler(browse_episodes_cb, pattern=r"^browse_episodes$"),
                CallbackQueryHandler(all_episodes_start, pattern=r"^all_episodes$"),
                CallbackQueryHandler(back_to_seasons, pattern=r"^back_to_seasons$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            TV_ALL_PICKING: [
                CallbackQueryHandler(all_episode_pick, pattern=r"^pick_\d+$"),
                CallbackQueryHandler(all_episode_pick, pattern=r"^skip_episode$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            PICKING: [
                CallbackQueryHandler(pick, pattern=r"^pick_\d+$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            LIST_MENU: [
                CallbackQueryHandler(list_type_pick, pattern=r"^list_type_\w+$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            LIST_BROWSING: [
                CallbackQueryHandler(list_page, pattern=r"^list_page_\d+$"),
                CallbackQueryHandler(list_pick_movie, pattern=r"^list_pick_\d+$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            LIST_PICKING: [
                CallbackQueryHandler(pick, pattern=r"^pick_\d+$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
        ],
        per_user=True,
        per_chat=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(confirm_delete_cb, pattern=r"^confirm_delete_[a-f0-9]+$"))
    application.add_handler(CallbackQueryHandler(delete_torrent_cb, pattern=r"^delete_[a-f0-9]+$"))
    application.add_handler(CallbackQueryHandler(cancel_delete_cb, pattern=r"^cancel_delete$"))
    application.add_handler(CommandHandler("jellyfin", jellyfin_info))
    application.add_handler(CommandHandler("subtitles", subtitles_all))
    application.job_queue.run_repeating(poll_downloads, interval=30, first=10)
    application.run_polling(timeout=10)


if __name__ == "__main__":
    main()
