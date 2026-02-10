"""
Command Handlers — /start, /help, /block, /unblock
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import ADVISOR_TELEGRAM_ID
from services.session import (
    user_sessions, blocked_users,
    get_or_init_session, load_session_from_profile,
    ONBOARD_AWAITING_PHONE,
)
from services.customer_db import lookup_by_telegram_id


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles /start command, including QR code scans.
    No password needed — goes straight to onboarding or welcome back.
    """
    user_id = update.effective_user.id
    is_scan = len(context.args) > 0 and context.args[0] == "scan"

    if is_scan:
        greeting = "Hey! 👋 I'm Anderson's assistant over at Rick Case Honda."
    else:
        greeting = "Hey there! 👋 Welcome to Rick Case Honda."

    # Check if they're already set up
    customer = lookup_by_telegram_id(user_id)
    if customer and customer["vehicles"]:
        user_sessions[user_id] = load_session_from_profile(user_id, customer)
        veh = customer["vehicles"][0]
        await update.message.reply_text(
            f"{greeting}\n\n"
            f"Good to see you again! I've got your "
            f"{veh['year']} {veh['make']} {veh['model']} loaded up.\n\n"
            f"What's going on with your car today?"
        )
    else:
        # New user — start onboarding
        session = get_or_init_session(user_id)
        session["onboarding"] = ONBOARD_AWAITING_PHONE

        await update.message.reply_text(
            f"{greeting}\n\n"
            f"Let me get you set up real quick — what's your phone number?"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /help command."""
    await update.message.reply_text(
        "Here's what I can help with:\n\n"
        "Got a question about your Civic, Ridgeline, or Passport? "
        "Just ask me — I've got the owner's manuals right here.\n\n"
        "Need to come in for service? Just say something like "
        "\"I need an oil change\" or \"can I schedule something for next week\" "
        "and I'll get you set up.\n\n"
        "I can also tell you about your vehicle's history, warranty status, "
        "and past service records if we have your Carfax on file.\n\n"
        "If you've been here before, I'll probably recognize your number "
        "so we can skip the back-and-forth. 👍"
    )


async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Advisor-only command to block a user.
    Usage: /block 123456789
    """
    user_id = update.effective_user.id

    if not ADVISOR_TELEGRAM_ID or user_id != ADVISOR_TELEGRAM_ID:
        await update.message.reply_text("This command is for the service advisor only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /block <telegram_user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid user ID.")
        return

    if target_id not in blocked_users:
        blocked_users.append(target_id)

    await update.message.reply_text(f"✅ Blocked user {target_id}. They won't be able to message the bot.")


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Advisor-only command to unblock a user.
    Usage: /unblock 123456789
    """
    user_id = update.effective_user.id

    if not ADVISOR_TELEGRAM_ID or user_id != ADVISOR_TELEGRAM_ID:
        await update.message.reply_text("This command is for the service advisor only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /unblock <telegram_user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid user ID.")
        return

    if target_id in blocked_users:
        blocked_users.remove(target_id)

    await update.message.reply_text(f"✅ Unblocked user {target_id}.")
