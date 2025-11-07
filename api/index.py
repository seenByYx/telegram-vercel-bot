import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# === Environment Variables ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1971125096"))

# === Initialize Telegram Bot ===
app = Application.builder().token(BOT_TOKEN).build()

# In-memory message tracking
message_links = {}   # admin_msg_id → { "user_id": ..., "user_msg_id": ... }
user_ids = set()
active_user = None


# === START Command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    if user_id == ADMIN_CHAT_ID:
        await update.message.reply_text("✅ Admin panel active.")
    else:
        user_ids.add(user_id)
        await update.message.reply_text("👋 Welcome! Send me a message — I'll forward it to the admin.")


# === USER → ADMIN ===
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global message_links
    msg = update.effective_message
    user_id = msg.chat.id
    user_ids.add(user_id)

    # Forward message to admin
    forwarded = await context.bot.forward_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=msg.message_id
    )

    # Store link
    message_links[forwarded.message_id] = {
        "user_id": user_id,
        "user_msg_id": msg.message_id
    }


# === ADMIN → USER ===
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_user
    msg = update.effective_message

    if msg.chat.id != ADMIN_CHAT_ID:
        return  # Ignore non-admin messages

    if msg.reply_to_message and msg.reply_to_message.message_id in message_links:
        # Admin replied to forwarded message
        link = message_links[msg.reply_to_message.message_id]
        user_id = link["user_id"]
        active_user = user_id
        await forward_to_user(context, msg, user_id, link["user_msg_id"])
    elif active_user:
        # Admin continuing conversation
        await forward_to_user(context, msg, active_user)
    else:
        await msg.reply_text("⚠️ No active user selected. Reply to a user's message first.")


# === Helper: Send message safely ===
async def forward_to_user(context, msg, user_id, reply_to_message_id=None):
    try:
        if msg.text:
            await context.bot.send_message(chat_id=user_id, text=msg.text, reply_to_message_id=reply_to_message_id)
        elif msg.photo:
            await context.bot.send_photo(chat_id=user_id, photo=msg.photo[-1].file_id, caption=msg.caption or "")
        elif msg.video:
            await context.bot.send_video(chat_id=user_id, video=msg.video.file_id, caption=msg.caption or "")
        elif msg.document:
            await context.bot.send_document(chat_id=user_id, document=msg.document.file_id, caption=msg.caption or "")
        elif msg.voice:
            await context.bot.send_voice(chat_id=user_id, voice=msg.voice.file_id, caption=msg.caption or "")
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=user_id, sticker=msg.sticker.file_id)
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"❌ Error sending to user: {e}")


# === DONATE Command ===
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💖 **Support this bot!**\n\n📱 UPI: `yxseen.email@okhdfcbank`\n💬 Thank you ❤️",
        parse_mode="Markdown"
    )


# === Register Handlers ===
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("donate", donate))
app.add_handler(MessageHandler(filters.Chat(ADMIN_CHAT_ID), handle_admin_reply))
app.add_handler(MessageHandler(~filters.Chat(ADMIN_CHAT_ID), handle_user_message))


# === Vercel Entry Function (Webhook) ===
def handler(request):
    """Vercel serverless entry point for Telegram webhook."""
    if request.method == "POST":
        try:
            data = request.get_json(force=True)
            update = Update.de_json(data, app.bot)
            app.process_update(update)
            return {"statusCode": 200, "body": "ok"}
        except Exception as e:
            return {"statusCode": 500, "body": str(e)}

    # GET request (status page)
    return {"statusCode": 200, "body": "🤖 Telegram Bot active on Vercel!"}
