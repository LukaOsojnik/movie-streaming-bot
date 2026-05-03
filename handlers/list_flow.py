import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes
from search import search_torrents, format_size
from tmdb import get_top_rated, get_popular, get_now_playing
from subtitles import check_subtitles_available
from handlers.common import require_auth, LIST_MENU, LIST_BROWSING, LIST_PICKING, LIST_PAGE_SIZE, SUBTITLE_CONFIRM


def _build_list_keyboard(movies: list[dict], page: int) -> tuple[str, InlineKeyboardMarkup]:
    total = (len(movies) + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE
    start = page * LIST_PAGE_SIZE
    page_movies = movies[start:start + LIST_PAGE_SIZE]

    lines = [f"🎬 Movies (Page {page + 1}/{total}):\n"]
    btn_row = []
    for i, m in enumerate(page_movies):
        rank = start + i + 1
        year_str = f" ({m['year']})" if m["year"] else ""
        rating_str = f" ⭐{m['rating']}" if m["rating"] else ""
        lines.append(f"{rank}. {m['title']}{year_str}{rating_str}")
        btn_row.append(InlineKeyboardButton(str(rank), callback_data=f"list_pick_{start + i}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"list_page_{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"list_page_{page + 1}"))

    keyboard = [r for r in [btn_row, nav, [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]] if r]
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


@require_auth
async def list_movies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("⭐ Top Rated (Top 250)", callback_data="list_type_top_rated")],
        [InlineKeyboardButton("🔥 Popular (Fan Favorites)", callback_data="list_type_popular")],
        [InlineKeyboardButton("🎟️ Now Playing", callback_data="list_type_now_playing")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await update.message.reply_text(
        "Which list would you like to browse?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return LIST_MENU


@require_auth
async def list_type_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    list_type = q.data.split("_", 2)[2]  # "list_type_top_rated" → "top_rated"

    fetch_fns = {
        "top_rated": get_top_rated,
        "popular": get_popular,
        "now_playing": get_now_playing,
    }
    await q.message.edit_text("⏳ Loading...")
    try:
        movies = fetch_fns[list_type]()
    except ConnectionError as e:
        await q.message.edit_text(str(e))
        return ConversationHandler.END

    if not movies:
        await q.message.edit_text("❌ No movies found.")
        return ConversationHandler.END

    context.user_data.update({"tmdb_movies": movies, "list_page": 0, "mode": "movies"})
    text, markup = _build_list_keyboard(movies, 0)
    await q.message.edit_text(text, reply_markup=markup)
    return LIST_BROWSING


@require_auth
async def list_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    page = int(q.data.split("_")[2])
    context.user_data["list_page"] = page
    text, markup = _build_list_keyboard(context.user_data["tmdb_movies"], page)
    await q.message.edit_text(text, reply_markup=markup)
    return LIST_BROWSING


@require_auth
async def list_pick_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    idx = int(q.data.split("_")[2])
    movie = context.user_data["tmdb_movies"][idx]
    title = movie["title"]
    context.user_data["mode"] = "movies"
    context.user_data["pending_query"] = title

    loop = asyncio.get_running_loop()
    available = await loop.run_in_executor(None, check_subtitles_available, title)

    if not available:
        context.user_data["subtitle_origin"] = "list"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, continue", callback_data="subtitle_yes"),
                InlineKeyboardButton("❌ No, cancel", callback_data="subtitle_no"),
            ]
        ])
        await q.message.reply_text(
            f"⚠️ No subtitles found for '{title}'. Continue anyway?",
            reply_markup=keyboard,
        )
        return SUBTITLE_CONFIRM

    await q.message.reply_text(f'🔍 Searching torrents for "{title}"...')
    try:
        results = search_torrents(title, "movies")
    except ConnectionError as e:
        await q.message.reply_text(str(e))
        return LIST_BROWSING
    if not results:
        await q.message.reply_text(f'❌ No torrents found for "{title}". Try another.')
        return LIST_BROWSING

    context.user_data["results"] = results
    lines = [f'🎬 Results for "{title}":\n']
    for i, r in enumerate(results, 1):
        size = format_size(int(r["size"]))
        lines.append(f"{i}. {r['name']}\n   🌱 {int(r['seeders'])} seeders · {size}")
    keyboard = [
        [InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}") for i in range(len(results))],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await q.message.reply_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    return LIST_PICKING
