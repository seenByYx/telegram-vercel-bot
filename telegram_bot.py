from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext
from telegram.ext import filters
import json
import os
import asyncio
import telegram

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
# === STORAGE ===
message_links = {}   # admin_message_id → {"user_id": ..., "user_msg_id": ...}
user_ids = set()
broadcast_waiting = {}
active_user = None

# --- ASYNC LOCK for safe writes ---
lock = asyncio.Lock()

# --- SAVE & LOAD HELPERS (with error handling) ---
async def safe_save(filename, data):
    async with lock:
        try:
            with open(filename, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving {filename}: {e}")

def safe_load(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename) as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Corrupt {filename}, resetting...")
            return default
    return default

def save_users():
    asyncio.create_task(safe_save("users.json", list(user_ids)))

def load_users():
    global user_ids
    data = safe_load("users.json", [])
    user_ids = set(data)

def save_links():
    asyncio.create_task(safe_save("message_links.json", message_links))

def load_links():
    global message_links
    data = safe_load("message_links.json", {})
    message_links = {int(k): v for k, v in data.items()}

def save_active_user():
    asyncio.create_task(safe_save("active_user.json", {"active_user": active_user}))

def load_active_user():
    global active_user
    data = safe_load("active_user.json", {"active_user": None})
    active_user = data.get("active_user")

# --- START ---
async def start(update: Update, context: CallbackContext):
    user_id = update.message.chat.id
    if user_id == ADMIN_CHAT_ID:
        return await update.message.reply_text("✅ Admin panel active.")
    user_ids.add(user_id)
    save_users()
    await update.message.reply_text("👋 Welcome! Send me anything — I’ll forward it to the admin.")

# --- USER → ADMIN ---
async def handle_user_message(update: Update, context: CallbackContext):
    global message_links
    msg = update.effective_message
    user_id = msg.chat.id
    user_ids.add(user_id)
    save_users()


    forwarded = await context.bot.forward_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=msg.message_id
    )

    # Store message link and prune old ones
    message_links[forwarded.message_id] = {
        "user_id": user_id,
        "user_msg_id": msg.message_id
    }
    if len(message_links) > 500:
        message_links = dict(list(message_links.items())[-500:])
    save_links()

# --- ADMIN → USER ---
async def handle_admin_reply(update: Update, context: CallbackContext):
    global active_user
    msg = update.message

    # --- Security check ---
    if msg.chat.id != ADMIN_CHAT_ID:
        return

    # --- Broadcast check ---
    if broadcast_waiting.get(ADMIN_CHAT_ID):
        try:
            await do_broadcast(update, context)
        finally:
            broadcast_waiting[ADMIN_CHAT_ID] = False
        return

    # --- If reply to user message ---
    if msg.reply_to_message and msg.reply_to_message.message_id in message_links:
        replied_id = msg.reply_to_message.message_id
        user_id = message_links[replied_id]["user_id"]
        user_msg_id = message_links[replied_id]["user_msg_id"]
        active_user = user_id
        save_active_user()
        await send_message_to_user(context, msg, user_id, user_msg_id)

    # --- If plain message (no reply) ---
    elif active_user:
        await send_message_to_user(context, msg, active_user)
    else:
        await msg.reply_text("⚠️ No active user selected. Reply to a user's message first to start chatting.")

# --- Helper: Send message to user safely ---
async def send_message_to_user(context: CallbackContext, msg, user_id, reply_to_message_id=None):
    try:
        if msg.text:
            await context.bot.send_message(chat_id=user_id, text=msg.text, reply_to_message_id=reply_to_message_id)
        elif msg.photo:
            await context.bot.send_photo(chat_id=user_id, photo=msg.photo[-1].file_id,
                                         caption=msg.caption or "", reply_to_message_id=reply_to_message_id)
        elif msg.video:
            await context.bot.send_video(chat_id=user_id, video=msg.video.file_id,
                                         caption=msg.caption or "", reply_to_message_id=reply_to_message_id)
        elif msg.document:
            await context.bot.send_document(chat_id=user_id, document=msg.document.file_id,
                                            caption=msg.caption or "", reply_to_message_id=reply_to_message_id)
        elif msg.voice:
            await context.bot.send_voice(chat_id=user_id, voice=msg.voice.file_id,
                                         caption=msg.caption or "", reply_to_message_id=reply_to_message_id)
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=user_id, sticker=msg.sticker.file_id,
                                           reply_to_message_id=reply_to_message_id)
    except telegram.error.Forbidden:
        await msg.reply_text("⚠️ User has blocked the bot or is unavailable.")
    except Exception as e:
        await msg.reply_text(f"❌ Failed to send: {e}")

# --- BROADCAST ---
async def broadcast_command(update: Update, context: CallbackContext):
    if update.message.chat.id != ADMIN_CHAT_ID:
        return await update.message.reply_text("🚫 You’re not authorized.")
    broadcast_waiting[ADMIN_CHAT_ID] = True
    await update.message.reply_text("📢 Send your broadcast message now.")

async def do_broadcast(update: Update, context: CallbackContext):
    msg = update.message
    sent_count = 0
    failed = 0
    for uid in user_ids:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=f"📢 *Announcement:*\n\n{msg.text}", parse_mode="Markdown")
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption="📢 Announcement")
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption="📢 Announcement")
            elif msg.document:
                await context.bot.send_document(chat_id=uid, document=msg.document.file_id, caption="📢 Announcement")
            elif msg.sticker:
                await context.bot.send_sticker(chat_id=uid, sticker=msg.sticker.file_id)
            elif msg.voice:
                await context.bot.send_voice(chat_id=uid, voice=msg.voice.file_id)
            sent_count += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Broadcast sent to {sent_count} users. ({failed} failed)")

# --- DONATE ---
async def donate(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "💖 **Support this bot!**\n\n📱 UPI: `yxseen.email@okhdfcbank`\n🌐 Razorpay: \n💬 Thank you ❤️",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

# --- MAIN ---
def main():
    load_users()
    load_links()
    load_active_user()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(MessageHandler(filters.Chat(ADMIN_CHAT_ID), handle_admin_reply))
    app.add_handler(MessageHandler(~filters.Chat(ADMIN_CHAT_ID), handle_user_message))

    print(f"🤖 Bot running... (Active user: {active_user})")
    app.run_polling()

if __name__ == "__main__":
    main()
