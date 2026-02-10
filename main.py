"""
Rick Case Honda AI Bot — Telegram Entry Point

This file ONLY handles:
  - Bot setup and configuration
  - Handler registration
  - Startup banner

All logic lives in:
  handlers/commands.py    → /start, /help, /block, /unblock
  handlers/messages.py    → Main message router (orchestrator dispatch)
  handlers/booking.py     → Appointment start/cancel/flow
  handlers/onboarding.py  → Phone → VIN collection for new customers
  handlers/documents.py   → Advisor Carfax PDF uploads
  services/session.py     → Shared state (sessions, appointments, rate limiting)
"""

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN, ADVISOR_TELEGRAM_ID
from utils.data_setup import setup_data_folder
from services.customer_database import customer_db

# Import handlers
from handlers.commands import start_command, help_command, block_command, unblock_command
from handlers.messages import handle_message
from handlers.booking import cancel_appointment
from handlers.documents import handle_document
from handlers.photos import handle_photo

# ─── Startup ──────────────────────────────────────────────────────
setup_data_folder()


# ─── Error Handler ────────────────────────────────────────────────

async def error_handler(update: Update, context):
    """Handles errors."""
    print(f"❌ Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry about that — something went wrong on my end. Try again, "
            "or you can always call us directly at the service desk."
        )


# ─── Entry Point ──────────────────────────────────────────────────

def main():
    """Start the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found in .env!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_appointment))
    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("unblock", unblock_command))

    # Photo handler (customer image uploads — recall letters, warning lights, etc.)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Document handler (Carfax PDF uploads from advisor)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Text message handler (everything else)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Error handler
    app.add_error_handler(error_handler)

    # Startup banner
    record_count = len(customer_db.df) if not customer_db.df.empty else 0
    unique_count = customer_db.df["PHONE"].nunique() if record_count > 0 else 0

    print(f"\n{'=' * 50}")
    print("🤖 RICK CASE HONDA AI BOT")
    print(f"{'=' * 50}")
    print(f"✅ Bot is running...")
    print(f"📊 Customer database: {record_count} records loaded")
    print(f"👥 Unique customers: {unique_count}")
    print(f"📅 Appointment scheduling: ENABLED")
    print(f"🔄 Returning customer detection: ENABLED")
    print(f"🧠 Orchestrator: ENABLED")
    print(f"📋 Carfax ingestion: ENABLED")
    if ADVISOR_TELEGRAM_ID:
        print(f"📧 Advisor notifications: ENABLED (ID: {ADVISOR_TELEGRAM_ID})")
    else:
        print("⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)")
    print(f"\nPress Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
