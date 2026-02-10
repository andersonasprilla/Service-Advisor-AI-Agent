"""
Booking Handlers — Start and cancel appointments.
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from services.session import user_sessions, appointment_data
from services.appointments import save_appointment, notify_advisor
from agents.booking_agent import booking_agent


async def start_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a conversational booking flow."""
    user_id = update.effective_user.id
    user_text = update.message.text
    session = user_sessions.get(user_id, {})

    appointment_data[user_id] = {
        "user_id": user_id,
        "telegram_username": update.effective_user.username,
        "messages": [],
    }

    # Pre-fill from session
    if session.get("customer_name"):
        appointment_data[user_id]["name"] = session["customer_name"]
    if session.get("phone"):
        appointment_data[user_id]["phone"] = session["phone"]
    if session.get("vehicle_label"):
        appointment_data[user_id]["vehicle"] = session["vehicle_label"]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply, is_complete = booking_agent.run(user_text, appointment_data[user_id], session)

    await update.message.reply_text(reply)

    if is_complete:
        await _finalize_appointment(update, context, user_id)


async def handle_booking_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Continue a mid-booking conversation.
    Returns True if we handled the message (caller should return early).
    """
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in appointment_data:
        return False

    # Handle cancel
    if user_text.strip().lower() in ["/cancel", "cancel", "cancelar", "nevermind"]:
        del appointment_data[user_id]
        session_lang = user_sessions.get(user_id, {}).get("language", "en")
        cancel_msgs = {
            "es": "Sin problema, lo cancelé. Avísame cuando quieras reagendar.",
            "pt": "Sem problema, cancelei. Me avisa quando quiser reagendar.",
        }
        msg = cancel_msgs.get(session_lang, "No worries, I cancelled that. Just let me know whenever you're ready to reschedule.")
        await update.message.reply_text(msg)
        return True

    # Continue booking conversation
    session_data = user_sessions.get(user_id, {})

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply, is_complete = booking_agent.run(user_text, appointment_data[user_id], session_data)

    await update.message.reply_text(reply)

    if is_complete:
        await _finalize_appointment(update, context, user_id)

    return True


async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel appointment booking via /cancel command."""
    user_id = update.effective_user.id
    appointment_data.pop(user_id, None)
    session = user_sessions.get(user_id, {})
    lang = session.get("language", "en")
    cancel_msgs = {
        "es": "Sin problema, lo cancelé. Avísame cuando quieras reagendar.",
        "pt": "Sem problema, cancelei. Me avisa quando quiser reagendar.",
    }
    msg = cancel_msgs.get(lang, "No worries, I cancelled that. Just let me know whenever you're ready to reschedule.")
    await update.message.reply_text(msg)
    return ConversationHandler.END


async def _finalize_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Save and notify for a completed appointment."""
    info = {k: v for k, v in appointment_data[user_id].items()
            if k not in ("_state", "messages")}
    info["user_id"] = user_id
    info["telegram_username"] = update.effective_user.username

    print(f"\n{'=' * 60}")
    print(f"💾 SAVING APPOINTMENT: {info.get('name')} / {info.get('phone')}")
    print(f"{'=' * 60}\n")

    save_appointment(info)
    await notify_advisor(context, info)
    del appointment_data[user_id]
