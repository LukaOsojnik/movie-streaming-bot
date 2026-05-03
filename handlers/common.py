import functools
import re
from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes
from config import ALLOWED_USERS

SEARCHING, PICKING, TV_SEASON, TV_EPISODE, TV_ALL_PICKING, LIST_MENU, LIST_BROWSING, LIST_PICKING, SUBTITLE_CONFIRM = range(9)
LIST_PAGE_SIZE = 10


def require_auth(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if ALLOWED_USERS and update.effective_user.id not in ALLOWED_USERS:
            await update.effective_message.reply_text("⛔ Unauthorized")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "-", name).strip()
