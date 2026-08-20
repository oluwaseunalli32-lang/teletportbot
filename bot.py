# bot.py – corrected version

import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import ReportPeerRequest  # <--- ADDED

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
ALLOWED_USERS = [int(x.strip()) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()]
# ----------------------------

telethon_client = None
logging.basicConfig(level=logging.INFO)

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return False
    return user_id in ALLOWED_USERS

async def start_telethon():
    global telethon_client
    if not SESSION_STRING:
        logging.error("SESSION_STRING is missing!")
        return False
    try:
        telethon_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await telethon_client.start()
        logging.info("Telethon client connected successfully.")
        return True
    except Exception as e:
        logging.error(f"Failed to connect Telethon: {e}")
        return False

# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    await update.message.reply_text(
        "✅ **Report Bot Active**\n\n"
        "**Usage:**\n"
        "`/report @target_username reason [count]`\n\n"
        "**Examples:**\n"
        "`/report @FakeChannel fake_account 100`\n"
        "`/report @Scammer spam 50`\n\n"
        "**Reasons:** `spam`, `fake_account`, `violence`, `pornography`",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    if telethon_client and telethon_client.is_connected():
        await update.message.reply_text("✅ Reporting account is **connected** and ready.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Reporting account is **disconnected**. Check your SESSION_STRING.", parse_mode="Markdown")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ **Usage:** `/report @username reason [count]`\n"
            "Example: `/report @FakeChannel fake_account 100`",
            parse_mode="Markdown"
        )
        return

    target = args[0].replace("@", "").strip()
    reason = args[1].strip().lower()
    count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 100
    count = min(count, 500)

    if not telethon_client or not telethon_client.is_connected():
        await update.message.reply_text("❌ Reporting client is not ready. Check `/status`.")
        return

    await update.message.reply_text(
        f"🔄 Starting report job...\n"
        f"Target: `{target}`\n"
        f"Reason: `{reason}`\n"
        f"Count: `{count}`\n\n"
        f"*This may take a few minutes.*",
        parse_mode="Markdown"
    )

    async def do_reports():
        try:
            entity = await telethon_client.get_entity(target)
            successful = 0
            for i in range(count):
                try:
                    # --- FIXED LINE ---
                    await telethon_client.invoke(ReportPeerRequest(peer=entity, reason=reason))
                    # --------------------
                    successful += 1
                except FloodWaitError as e:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏳ Rate limited. Waiting {e.seconds} seconds..."
                    )
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logging.error(f"Report failed: {e}")
                    await asyncio.sleep(1)
                await asyncio.sleep(0.8)

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ **Finished!**\nSent `{successful}` reports to `{target}` for `{reason}`.",
                parse_mode="Markdown"
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ **Error:** `{str(e)}`",
                parse_mode="Markdown"
            )

    asyncio.create_task(do_reports())

# --- Main ---

async def main():
    if not all([BOT_TOKEN, API_ID, API_HASH, SESSION_STRING]):
        logging.error("Missing required environment variables!")
        return

    if not ALLOWED_USERS:
        logging.warning("ALLOWED_USERS is empty! No one can use the bot.")

    await start_telethon()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("report", cmd_report))

    logging.info("Bot is starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
