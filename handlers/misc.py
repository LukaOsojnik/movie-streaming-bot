import asyncio
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes
from qbit import get_torrents, delete_torrent
from config import JELLYFIN_PUBLIC_URL
from subtitles import fetch_subtitles_all
from handlers.common import require_auth, SEARCHING

_STOP = re.compile(
    r'^('
    r'2160p|1080p|1080i|720p|720i|480p|4[Kk]|UHD|'
    r'BluRay|Blu-Ray|BDRip|BDRemux|BRRip|'
    r'WEB[\-\.]?DL|WEBRip|WEB|HDRip|DVDRip|DVD|HDTV|PDTV|VOD|'
    r'NF|AMZN|DSNP|HMAX|ATVP|'
    r'x\.?264|x\.?265|H\.?264|H\.?265|HEVC|AVC|XviD|DivX|'
    r'HDR10?|DV|DoVi|SDR|REMUX|HDR|'
    r'AAC|AC3|DTS|EAC3|TrueHD|FLAC|MP3|Atmos|DD[P+]?\d*|DDP\d*|'
    r'REPACK|PROPER|EXTENDED|THEATRICAL|UNRATED|DIRECTORS|'
    r'MULTI|DUAL|DUBBED|SUBBED|ENGLISH|HINDI|FRENCH|GERMAN|SPANISH|'
    r'YIFY|YTS|RARBG'
    r')$',
    re.IGNORECASE,
)
_JUNK = re.compile(r'[\[\]{}]|^\d{1,3}[-.]', re.IGNORECASE)
_EP = re.compile(r'^[Ss]\d{1,2}[Ee]\d{1,2}', re.IGNORECASE)


def _parse_title(name: str) -> str:
    year_m = re.search(r'\b(19\d{2}|20[012]\d)\b', name)
    if year_m:
        before = name[:year_m.start()]
        title = re.sub(r'[\._]+', ' ', before).strip(' .-_')
        return f"{title} ({year_m.group(1)})" if title else name

    tokens = re.split(r'[\._\s]+', name)
    parts = []
    for tok in tokens:
        ep = _EP.match(tok)
        if ep:
            parts.append(ep.group().upper())
            break
        if _STOP.match(tok) or _JUNK.search(tok):
            break
        parts.append(tok)
    return ' '.join(parts) or name


def _bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)



@require_auth
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Movie Download Bot!\n\n"
        "Here are all available commands:\n\n"
        "🎬 /movies — Search for a movie by title. You'll get a list of torrent results with seeder counts and file sizes to choose from.\n\n"
        "📺 /tv — Search for a TV show by title. Pick a season, then choose a specific episode or download all episodes in that season at once.\n\n"
        "📋 /list — Browse curated IMDB movie lists:\n"
        "   • ⭐ Top Rated — IMDB Top 250 films\n"
        "   • 🔥 Popular — Fan favorites right now\n"
        "   • 🎟️ Now Playing — Currently in cinemas\n"
        "   Pick any movie from the list to search and download it.\n\n"
        "📥 /status — Show all active and completed downloads with progress percentages and ETA.\n\n"
        "🎬 /jellyfin — Show the Jellyfin server address.\n\n"
        "🔤 /subtitles — Download missing English & Croatian subtitles for all movies and TV shows.\n\n"
        "❓ /start — Show this help message again."
    )


@require_auth
async def movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "movies"
    await update.message.reply_text("🎬 Send me a movie title to search:")
    return SEARCHING


@require_auth
async def tv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "tv"
    await update.message.reply_text("📺 Send me a TV show title to search:")
    return SEARCHING


def _format_status_message(active: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["⬇️ Downloading\n"]
    buttons = []
    for i, t in enumerate(active, start=1):
        title = _parse_title(t["name"])
        pct = float(t["progress"].rstrip('%'))
        bar = _bar(pct)
        eta_sec = t["eta"]
        if eta_sec and eta_sec < 8640000:
            h, rem = divmod(eta_sec, 3600)
            m = rem // 60
            eta_str = f" · ETA {h}h{m:02d}m" if h else f" · ETA {m}m"
        else:
            eta_str = ""
        lines.append(f"{i}. {title}")
        lines.append(f"{bar} {t['progress']}{eta_str}\n")
        short = title[:30] + "…" if len(title) > 30 else title
        buttons.append([InlineKeyboardButton(f"🗑️ {i}. {short}", callback_data=f"delete_{t['hash']}")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


@require_auth
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        torrents = get_torrents()
    except ConnectionError as e:
        await update.message.reply_text(str(e))
        return

    active = [t for t in torrents if t["progress"] != "Done"]

    if not active:
        await update.message.reply_text("📭 Nothing downloading right now.")
        return

    text, markup = _format_status_message(active)
    await update.message.reply_text(text, reply_markup=markup)


@require_auth
async def delete_torrent_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    info_hash = query.data.split("_", 1)[1]

    try:
        torrents = get_torrents()
    except ConnectionError as e:
        await query.message.reply_text(str(e))
        return

    torrent = next((t for t in torrents if t["hash"] == info_hash), None)
    if not torrent:
        await query.edit_message_text("⚠️ Torrent not found — it may have already been removed.")
        return

    title = _parse_title(torrent["name"])
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_delete_{info_hash}"),
            InlineKeyboardButton("❌ No, keep", callback_data="cancel_delete"),
        ]
    ])
    await query.edit_message_text(
        f"🗑️ Delete \"{title}\" and remove its files?",
        reply_markup=keyboard,
    )


@require_auth
async def confirm_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    info_hash = query.data.split("_", 2)[2]

    try:
        delete_torrent(info_hash, delete_files=True)
        await query.edit_message_text("✅ Torrent deleted.")
    except ConnectionError as e:
        await query.edit_message_text(str(e))


@require_auth
async def cancel_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")


@require_auth
async def jellyfin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎬 Jellyfin: {JELLYFIN_PUBLIC_URL}")


@require_auth
async def subtitles_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Scanning library for missing subtitles — this may take a while...")
    loop = asyncio.get_running_loop()
    try:
        downloaded, failed = await loop.run_in_executor(None, fetch_subtitles_all)
        parts = []
        if downloaded:
            parts.append(f"✅ Downloaded subtitles for {len(downloaded)} item(s):\n" + "\n".join(f"• {l}" for l in downloaded))
        if failed:
            parts.append(f"⚠️ Failed for {len(failed)} item(s) (likely rate limited):\n" + "\n".join(f"• {l}" for l in failed))
        if not parts:
            parts.append("✅ Done — no missing subtitles found.")
        await update.message.reply_text("\n\n".join(parts))
    except Exception as e:
        logging.warning("Full subtitle scan failed: %s", e)
        await update.message.reply_text(f"⚠️ Subtitle scan failed: {e}")


@require_auth
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Cancelled.")
    return ConversationHandler.END
