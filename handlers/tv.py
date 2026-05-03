import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes
from search import get_episode_numbers, get_episode_results, get_season_pack_results, search_season_episodes, build_magnet, format_size
from qbit import add_torrent, torrent_exists
from jellyfin import find_shared_by_title
from config import QB_TV_DIR
from handlers.common import require_auth, _safe_name, TV_SEASON, TV_EPISODE, TV_ALL_PICKING, PICKING


@require_auth
async def season_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    season = int(query_cb.data.split("_")[1])
    show = context.user_data["tv_query"]
    context.user_data["tv_season"] = season

    episodes = get_episode_numbers(context.user_data["tv_results"], season)

    if not episodes:
        await query_cb.message.reply_text(f"🔍 Searching for individual episodes of Season {season}...")
        try:
            loop = asyncio.get_running_loop()
            episodes, fresh_results = await loop.run_in_executor(None, search_season_episodes, show, season)
            if fresh_results:
                existing_hashes = {r["info_hash"] for r in context.user_data["tv_results"]}
                context.user_data["tv_results"].extend(
                    r for r in fresh_results if r["info_hash"] not in existing_hashes
                )
        except ConnectionError as e:
            await query_cb.message.reply_text(str(e))
            return TV_SEASON

    if not episodes:
        packs = get_season_pack_results(show, season, context.user_data["tv_results"])
        if not packs:
            await query_cb.message.reply_text(f"❌ Nothing found for Season {season}. Try another season.")
            return TV_SEASON
        context.user_data["results"] = packs
        context.user_data["is_season_pack"] = True
        lines = [f'📦 No individual episodes found — Season {season} packs for "{show}":\n']
        for i, r in enumerate(packs, start=1):
            size = format_size(int(r["size"]))
            lines.append(f"{i}. {r['name']}\n   🌱 {int(r['seeders'])} seeders · {size}")
        keyboard = [
            [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(packs))],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]
        await query_cb.message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        return PICKING

    packs = get_season_pack_results(show, season, context.user_data["tv_results"])

    if packs:
        context.user_data["tv_episodes"] = episodes
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 Season Pack", callback_data="season_pack"),
                InlineKeyboardButton("📺 Individual Episodes", callback_data="browse_episodes"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ])
        await query_cb.message.reply_text(
            f'📺 "{show}" Season {season} — how do you want to download?',
            reply_markup=keyboard,
        )
        return TV_EPISODE

    await _render_episode_picker(query_cb.message, show, season, episodes)
    return TV_EPISODE


async def _render_episode_picker(message, show: str, season: int, episodes: list[int]):
    rows = [
        [InlineKeyboardButton(f"E{e:02d}", callback_data=f"episode_{e}") for e in episodes[i:i+6]]
        for i in range(0, len(episodes), 6)
    ]
    rows.append([InlineKeyboardButton("📥 All Episodes", callback_data="all_episodes")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_seasons"), InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await message.reply_text(
        f'📺 "{show}" Season {season} — pick an episode:',
        reply_markup=InlineKeyboardMarkup(rows),
    )


@require_auth
async def browse_episodes_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()
    show = context.user_data["tv_query"]
    season = context.user_data["tv_season"]
    episodes = context.user_data.get("tv_episodes", [])
    await _render_episode_picker(query_cb.message, show, season, episodes)
    return TV_EPISODE


@require_auth
async def back_to_seasons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    query = context.user_data["tv_query"]
    seasons = context.user_data["tv_seasons"]
    rows = [
        [InlineKeyboardButton(f"Season {s}", callback_data=f"season_{s}") for s in seasons[i:i+4]]
        for i in range(0, len(seasons), 4)
    ]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await query_cb.message.reply_text(
        f'📺 Found seasons for "{query}". Pick one:',
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return TV_SEASON


@require_auth
async def episode_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    episode = int(query_cb.data.split("_")[1])
    show = context.user_data["tv_query"]
    season = context.user_data["tv_season"]

    results = get_episode_results(show, season, episode, context.user_data["tv_results"])

    if not results:
        await query_cb.message.reply_text(f"❌ No results found for S{season:02d}E{episode:02d}")
        return ConversationHandler.END

    context.user_data["results"] = results

    lines = [f'📺 Results for "{show}" S{season:02d}E{episode:02d}:\n']
    for i, r in enumerate(results, start=1):
        size = format_size(int(r["size"]))
        seeders = int(r["seeders"])
        lines.append(f"{i}. {r['name']}\n   🌱 {seeders} seeders · {size}")

    keyboard = [
        [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await query_cb.message.reply_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PICKING


async def _show_next_all_episode(message, context):
    show = context.user_data["tv_query"]
    season = context.user_data["tv_season"]
    queue = context.user_data["episodes_queue"]

    while queue:
        episode = queue.pop(0)
        context.user_data["current_episode"] = episode
        results = get_episode_results(show, season, episode, context.user_data["tv_results"])
        if not results:
            await message.reply_text(f"⚠️ No results for S{season:02d}E{episode:02d}, skipping...")
            continue

        context.user_data["results"] = results
        remaining = len(queue)
        header = f'📺 "{show}" S{season:02d}E{episode:02d}'
        header += f" — {remaining} more after this:" if remaining else ":"

        lines = [header + "\n"]
        for i, r in enumerate(results, start=1):
            size = format_size(int(r["size"]))
            seeders = int(r["seeders"])
            lines.append(f"{i}. {r['name']}\n   🌱 {seeders} seeders · {size}")

        keyboard = [
            [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
            [InlineKeyboardButton("⏭ Skip", callback_data="skip_episode"),
             InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]
        await message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        return TV_ALL_PICKING

    await message.reply_text("✅ All episodes queued!")
    return ConversationHandler.END


@require_auth
async def all_episodes_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    season = context.user_data["tv_season"]
    episodes = get_episode_numbers(context.user_data["tv_results"], season)
    context.user_data["episodes_queue"] = list(episodes)
    return await _show_next_all_episode(query_cb.message, context)


@require_auth
async def all_episode_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    if query_cb.data != "skip_episode":
        idx = int(query_cb.data.split("_")[1])
        results = context.user_data.get("results", [])
        if idx < len(results):
            r = results[idx]
            magnet = build_magnet(r["info_hash"], r["name"])
            info_hash = r["info_hash"]
            torrent_name = r["name"]
            show = _safe_name(context.user_data.get("tv_query", "Unknown"))
            season = context.user_data.get("tv_season", 1)
            scan_dir = f"{QB_TV_DIR}/{show}/Season {season:02d}"
            try:
                existing = find_shared_by_title(torrent_name, scan_dir)
                if existing:
                    await query_cb.message.reply_text(f"✓ Already downloaded: {os.path.basename(existing)}")
                else:
                    if not torrent_exists(info_hash):
                        add_torrent(magnet, save_path=scan_dir, category="TV")
                    await query_cb.message.reply_text(f"✓ Added: {torrent_name}")
            except ConnectionError as e:
                await query_cb.message.reply_text(str(e))
            except RuntimeError as e:
                await query_cb.message.reply_text(f"✗ qBittorrent error: {e}")
    else:
        season = context.user_data["tv_season"]
        ep = context.user_data["current_episode"]
        await query_cb.message.reply_text(f"⏭ Skipped S{season:02d}E{ep:02d}")

    return await _show_next_all_episode(query_cb.message, context)


@require_auth
async def season_pack_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_cb = update.callback_query
    await query_cb.answer()

    show = context.user_data["tv_query"]
    season = context.user_data["tv_season"]

    results = get_season_pack_results(show, season, context.user_data["tv_results"])

    if not results:
        await query_cb.message.reply_text(f"❌ No season pack found for Season {season}.")
        return TV_EPISODE

    context.user_data["results"] = results
    context.user_data["is_season_pack"] = True

    lines = [f'📦 Season {season} packs for "{show}":\n']
    for i, r in enumerate(results, start=1):
        size = format_size(int(r["size"]))
        lines.append(f"{i}. {r['name']}\n   🌱 {int(r['seeders'])} seeders · {size}")

    keyboard = [
        [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await query_cb.message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    return PICKING
