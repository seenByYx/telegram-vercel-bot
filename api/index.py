from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio
import json
import os
import telegram

# Environment variables (set in Vercel dashboard)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1971125096"))

# === STORAGE ===
message_links = {}
user_ids = set()
broadcast_waiting = {}
active_user = None
lock = asyncio.Lock()

# --- Basic Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat.id
    if user_id == ADMIN_CHAT_ID:
        await update.message.reply_text("✅ Admin panel active.")
    else:
        user_ids.add(user_id)
        await update.message.reply_text("👋 Welcome! Send me anything — I’ll forward it to the admin.")

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = msg.chat.id
    user_ids.add(user_id)

    forwarded = await context.bot.forward_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=msg.message_id
    )
    message_links[forwarded.message_id] = {"user_id": user_id, "user_msg_id": msg.message_id}

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_user
    msg = update.message
    if msg.chat.id != ADMIN_CHAT_ID:
        return

    if msg.reply_to_message and msg.reply_to_message.message_id in message_links:
        replied_id = msg.reply_to_message.message_id
        user_id = message_links[replied_id]["user_id"]
        user_msg_id = message_links[replied_id]["user_msg_id"]
        active_user = user_id
        await send_message_to_user(context, msg, user_id, user_msg_id)
    elif active_user:
        await send_message_to_user(context, msg, active_user)
    else:
        await msg.reply_text("⚠️ Reply to a user’s message first to select them.")

async def send_message_to_user(context, msg, user_id, reply_to_message_id=None):
    try:
        if msg.text:
            await context.bot.send_message(chat_id=user_id, text=msg.text, reply_to_message_id=reply_to_message_id)
        elif msg.photo:
            await context.bot.send_photo(chat_id=user_id, photo=msg.photo[-1].file_id,
                                         caption=msg.caption or "", reply_to_message_id=reply_to_message_id)
    except telegram.error.Forbidden:
        await msg.reply_text("⚠️ User has blocked the bot or is unavailable.")
    except Exception as e:
        await msg.reply_text(f"❌ Failed to send: {e}")

# --- Flask Web App for Vercel ---
flask_app = Flask(__name__)
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.Chat(ADMIN_CHAT_ID), handle_admin_reply))
app.add_handler(MessageHandler(~filters.Chat(ADMIN_CHAT_ID), handle_user_message))

@flask_app.route("/", methods=["GET"])
def home():
    return "✅ Bot is running on Vercel"

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), app.bot)
    app.update_queue.put_nowait(update)
    return "ok", 200

async def set_webhook():
    url = f"https://{os.getenv('VERCEL_URL')}/{BOT_TOKEN}"
    await app.bot.set_webhook(url)
    print(f"🌍 Webhook set to: {url}")

# --- Vercel Entry Point ---
def handler(request):
    return flask_app(request)
