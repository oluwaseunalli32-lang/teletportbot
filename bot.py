import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

# --- Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
SESSION_STRINGS = [s.strip() for s in os.environ.get("SESSION_STRINGS", "").split(",") if s.strip()]
ALLOWED_USERS = [int(x.strip()) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8443))
# -----------------------------

MAX_ACCOUNTS = 10
telethon_clients = {}  # index -> TelegramClient
logging.basicConfig(level=logging.INFO)

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return False
    return user_id in ALLOWED_USERS

async def get_telethon_client(index: int):
    """Return a connected Telethon client for account index."""
    if index in telethon_clients and telethon_clients[index].is_connected():
        return telethon_clients[index]

    if index >= len(SESSION_STRINGS):
        logging.error(f"Account index {index} out of range (only {len(SESSION_STRINGS)} sessions).")
        return None

    session_str = SESSION_STRINGS[index]
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await client.start()
        telethon_clients[index] = client
        logging.info(f"Account {index+1} connected.")
        return client
    except Exception as e:
        logging.error(f"Account {index+1} failed to connect: {e}")
        return None

def get_report_reason(reason_str: str):
    """Map string to Telethon report reason type."""
    reason_map = {
        "spam": "InputReportReasonSpam",
        "fake_account": "InputReportReasonOther",
        "violence": "InputReportReasonViolence",
        "pornography": "InputReportReasonPornography",
        "child_abuse": "InputReportReasonChildAbuse",
        "illegal_drugs": "InputReportReasonIllegalDrugs",
        "personal_details": "InputReportReasonPersonalDetails",
        "copyright": "InputReportReasonCopyright",
        "geo_irrelevant": "InputReportReasonGeoIrrelevant",
        "other": "InputReportReasonOther",
    }
    class_name = reason_map.get(reason_str, "InputReportReasonOther")
    reason_class = getattr(types, class_name, types.InputReportReasonOther)
    return reason_class()

# --- Command Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await update.message.reply_text(
        "✅ **10‑Account Report Bot Active**\n\n"
        f"**Accounts configured:** {len(SESSION_STRINGS)} / {MAX_ACCOUNTS}\n\n"
        "**Usage:**\n"
        "`/report @target reason [count]`\n"
        "`/testreport @target reason` – send 1 test report\n"
        "`/status` – check all accounts\n\n"
        "**Reasons:** `spam`, `fake_account`, `violence`, `pornography`, "
        "`child_abuse`, `illegal_drugs`, `personal_details`, `copyright`, "
        "`geo_irrelevant`, `other`",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    lines = []
    for i in range(len(SESSION_STRINGS)):
        client = await get_telethon_client(i)
        if client and client.is_connected():
            lines.append(f"Account {i+1}: ✅ Connected")
        else:
            lines.append(f"Account {i+1}: ❌ Disconnected")

    await update.message.reply_text(
        "**Account Status**\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

async def cmd_testreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send one report to verify the system works."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Unauthorized.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/testreport @username reason`", parse_mode="Markdown")
        return

    target = args[0].replace("@", "").strip()
    reason_str = args[1].strip().lower()

    await update.message.reply_text(f"🔬 Testing report on `{target}` with reason `{reason_str}`...", parse_mode="Markdown")

    client = await get_telethon_client(0)
    if not client:
        await update.message.reply_text("❌ No account available for testing.")
        return

    try:
        entity = await client.get_entity(target)
        await client(functions.account.ReportPeerRequest(
            peer=entity,
            reason=get_report_reason(reason_str),
            message=""
        ))
        await update.message.reply_text("✅ Test report sent successfully! The API call returned without error.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Test report failed: `{str(e)}`", parse_mode="Markdown")

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
    reason_str = args[1].strip().lower()
    count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 100
    count = min(count, 1000)

    if len(SESSION_STRINGS) == 0:
        await update.message.reply_text("❌ No reporting accounts configured.")
        return

    await update.message.reply_text(
        f"🔄 Starting report job...\nTarget: `{target}`\nReason: `{reason_str}`\nCount: `{count}`\nAccounts: {len(SESSION_STRINGS)}\n\n*This may take a few minutes.*",
        parse_mode="Markdown"
    )

    async def do_reports():
        try:
            # Get entity using first available account
            first_client = await get_telethon_client(0)
            if not first_client:
                await context.bot.send_message(chat_id=user_id, text="❌ Could not connect to first account.")
                return

            entity = await first_client.get_entity(target)
            successful = 0
            failed = 0

            for i in range(count):
                account_index = i % len(SESSION_STRINGS)
                client = await get_telethon_client(account_index)
                if not client:
                    failed += 1
                    logging.warning(f"Account {account_index+1} unavailable, skipping report {i+1}.")
                    continue

                try:
                    await client(functions.account.ReportPeerRequest(
                        peer=entity,
                        reason=get_report_reason(reason_str),
                        message=""
                    ))
                    successful += 1
                    logging.info(f"Report {i+1}/{count} sent via account {account_index+1}.")
                except FloodWaitError as e:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏳ Account {account_index+1} rate limited. Waiting {e.seconds}s..."
                    )
                    await asyncio.sleep(e.seconds)
                    failed += 1
                except Exception as e:
                    logging.error(f"Account {account_index+1} report failed: {e}")
                    failed += 1
                    await asyncio.sleep(1)

                await asyncio.sleep(0.8)

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ **Finished!**\nSent `{successful}` reports successfully. Failed: `{failed}`.\nTarget: `{target}` | Reason: `{reason_str}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"❌ **Error:** `{str(e)}`", parse_mode="Markdown")

    asyncio.create_task(do_reports())

# --- Main Entry (Webhook) ---
if __name__ == "__main__":
    if not all([BOT_TOKEN, API_ID, API_HASH, SESSION_STRINGS, WEBHOOK_URL]):
        logging.error("Missing required environment variables!")
        exit(1)

    if not ALLOWED_USERS:
        logging.warning("ALLOWED_USERS is empty! No one can use the bot.")

    if len(SESSION_STRINGS) > MAX_ACCOUNTS:
        logging.warning(f"You provided {len(SESSION_STRINGS)} sessions, but only first {MAX_ACCOUNTS} will be used.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("testreport", cmd_testreport))
    app.add_handler(CommandHandler("report", cmd_report))

    logging.info(f"Starting webhook server on port {PORT}...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=WEBHOOK_URL + "/" + BOT_TOKEN
    )
