"""
Rick Case Honda AI Bot — Telegram Entry Point

This file only handles:
  - Telegram handlers (start, help, messages)
  - Appointment conversation flow (state machine)
  - Delegating to agents for actual logic

All business logic lives in agents/ and services/.
"""

import os
import re
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler,
)

from config import TELEGRAM_BOT_TOKEN, SHOP_PASSWORD, ADVISOR_TELEGRAM_ID, VEHICLE_NAMESPACES
from utils.data_setup import setup_data_folder
from services.customer_database import customer_db
from services.appointments import save_appointment, notify_advisor
from agents import tech_agent, orchestrator

# ─── Startup ──────────────────────────────────────────────────────
setup_data_folder()

# ─── Conversation States ──────────────────────────────────────────
CONFIRM_IDENTITY, ASKING_PHONE, ASKING_VEHICLE, ASKING_SERVICE, ASKING_DATE, ASKING_TIME = range(6)

# ─── In-Memory State ─────────────────────────────────────────────
allowed_users = []          # Authenticated Telegram user IDs
user_sessions = {}          # vehicle context per user (for tech questions)
appointment_data = {}       # partial appointment info during booking


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMAND HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command, including QR code scans."""
    user_id = update.effective_user.id
    is_scan = len(context.args) > 0 and context.args[0] == "scan"

    greeting = (
        "Hi! This is Anderson's AI assistant. How can I help you? 🚗"
        if is_scan
        else "👋 Welcome to Rick Case Honda Service AI!"
    )

    if user_id not in allowed_users:
        await update.message.reply_text(f"{greeting}\n\n🔐 To get started, please send the shop password.")
    else:
        await update.message.reply_text(
            f"{greeting}\n\n💬 Ask me any Honda questions or type 'book appointment' to schedule service!"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /help command."""
    await update.message.reply_text(
        "🚗 Rick Case Honda Service AI\n\n"
        "I can help you with:\n\n"
        "📚 Technical Questions:\n"
        "• 2025 Honda Civic\n"
        "• 2025 Honda Ridgeline\n"
        "• 2026 Honda Passport\n\n"
        "📅 Quick Appointment Scheduling:\n"
        "• Say 'book appointment' or 'schedule service'\n"
        "• If you're a returning customer, I'll recognize you!\n\n"
        "💡 Tips:\n"
        "• Just mention your car model in your question\n"
        "• Example: 'What's the oil capacity for my Civic?'\n"
        "• I'll remember which car you're asking about!\n\n"
        "Just ask me anything!"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN MESSAGE HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all incoming text messages."""
    user_id = update.effective_user.id
    user_text = update.message.text

    print(f"📩 Received from {user_id} (@{update.effective_user.username}): {user_text}")

    if not ADVISOR_TELEGRAM_ID:
        print(f"💡 TIP: Set ADVISOR_TELEGRAM_ID={user_id} in .env to receive notifications!")

    # ── Check if mid-appointment flow ──
    if user_id in appointment_data and "_state" in appointment_data[user_id]:
        return await _route_appointment_state(update, context)

    # ── Auth check ──
    if user_id not in allowed_users:
        if user_text.strip().upper() == SHOP_PASSWORD:
            allowed_users.append(user_id)
            await update.message.reply_text(
                "✅ Access Granted! Welcome to Rick Case Honda!\n\n"
                "I'm ready to help. What's on your mind? (Civic, Passport, or Ridgeline)"
            )
        else:
            await update.message.reply_text(
                "I'd love to help you with that! 🛠️\n\n"
                "Please send the **shop password** first so I can access our manuals "
                "and booking system for you."
            )
        return

    # ── Appointment intent ──
    if router.detect_appointment_intent(user_text):
        return await start_appointment(update, context)

    # ── Escalation guard ──
    if router.check_for_escalation(user_text):
        await update.message.reply_text(
            "I understand. I have flagged this for a service advisor. "
            "Someone will reach out shortly. Is there anything else I can help with?"
        )
        return

    # ── Vehicle detection + RAG ──
    detected_car = router.identify_vehicle(user_text)
    target_car = None

    print(f"🔍 Detected vehicle: {detected_car}")

    # Direct vehicle selection (user just says "Civic")
    user_lower = user_text.strip().lower()
    if user_lower in VEHICLE_NAMESPACES:
        target_car = VEHICLE_NAMESPACES[user_lower]
        user_sessions[user_id] = target_car
        await update.message.reply_text(
            f"✅ Got it! I'll help you with your {user_lower.title()}.\n\nWhat would you like to know?"
        )
        return

    # Use detected or session vehicle
    if detected_car != "unknown":
        target_car = detected_car
        user_sessions[user_id] = target_car
    elif user_id in user_sessions:
        target_car = user_sessions[user_id]

    # ── Answer from manual ──
    if target_car:
        print(f"🔎 Searching manual: namespace={target_car}")
        answer = tech_agent.run(user_text, namespace=target_car)

        if "NO_ANSWER_FOUND" in answer:
            await update.message.reply_text(
                "I checked the manual, but I couldn't find that specific detail. "
                "Would you like to schedule an appointment to speak with a technician?"
            )
        else:
            vehicle_name = target_car.replace("-", " ").title()
            await update.message.reply_text(
                f"📖 {vehicle_name} Manual:\n\n{answer}\n\nNeed anything else about this vehicle?"
            )
    else:
        await update.message.reply_text(
            "I can help! Which vehicle is this for?\n"
            "• Passport\n• Civic\n• Ridgeline\n\n"
            "Just reply with the model name."
        )


async def _route_appointment_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route to the correct appointment handler based on current state."""
    user_id = update.effective_user.id
    state = appointment_data[user_id]["_state"]
    state_handlers = {
        "ASKING_PHONE": get_phone,
        "CONFIRM_IDENTITY": confirm_identity,
        "ASKING_VEHICLE": get_vehicle,
        "ASKING_SERVICE": get_service,
        "ASKING_DATE": get_date,
        "ASKING_TIME": get_time,
    }
    handler = state_handlers.get(state)
    if handler:
        return await handler(update, context)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPOINTMENT CONVERSATION HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the appointment booking flow."""
    user_id = update.effective_user.id
    appointment_data[user_id] = {
        "user_id": user_id,
        "telegram_username": update.effective_user.username,
        "_state": "ASKING_PHONE",
    }

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(text="📲 Share My Phone Number", request_contact=True)]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "📅 Great! Let me help you schedule an appointment.\n\n"
        "Please press the button below to share your number, or type it in manually.",
        reply_markup=keyboard,
    )
    return ASKING_PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect phone number via contact button or text."""
    user_id = update.effective_user.id
    phone = None

    if update.message.contact:
        digits = re.sub(r"\D", "", update.message.contact.phone_number)
        if len(digits) > 10:
            digits = digits[-10:]
        phone = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    else:
        phone = router.extract_phone(update.message.text)

    if not phone:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(text="📲 Share My Phone Number", request_contact=True)]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )
        await update.message.reply_text(
            "I couldn't find a phone number. Please use the button or type it (e.g., 954-243-1238).",
            reply_markup=keyboard,
        )
        return ASKING_PHONE

    customer = customer_db.search_by_phone(phone)

    if customer:
        appointment_data[user_id].update({
            "name": customer["name"],
            "phone": customer["phone"],
            "is_returning": True,
            "visit_count": customer["visit_count"],
            "all_vehicles": customer["all_vehicles"],
            "last_service": customer["last_service"],
            "_state": "ASKING_VEHICLE",
        })
        await update.message.reply_text(
            f"👋 Welcome back, {customer['name']}!\n\n"
            f"I see you last brought in your {customer['last_vehicle']}.\n"
            f"Is this the vehicle you'd like to service today?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASKING_VEHICLE

    appointment_data[user_id]["phone"] = phone
    appointment_data[user_id]["is_returning"] = False
    appointment_data[user_id]["_state"] = "CONFIRM_IDENTITY"

    await update.message.reply_text("Thanks! What's your name?", reply_markup=ReplyKeyboardRemove())
    return CONFIRM_IDENTITY


async def confirm_identity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect customer name (new customers only)."""
    user_id = update.effective_user.id
    appointment_data[user_id]["name"] = update.message.text.strip()
    appointment_data[user_id]["is_returning"] = False
    appointment_data[user_id]["_state"] = "ASKING_VEHICLE"

    await update.message.reply_text(
        "Perfect! What vehicle will you be bringing in?\n"
        "(e.g., '2024 Civic', 'Passport', '2022 Accord')"
    )
    return ASKING_VEHICLE


async def get_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect vehicle information."""
    user_id = update.effective_user.id
    user_text = update.message.text.strip().lower()

    if appointment_data[user_id].get("is_returning") and user_text in ["yes", "yeah", "yep", "correct"]:
        customer = customer_db.search_by_phone(appointment_data[user_id]["phone"])
        appointment_data[user_id]["vehicle"] = customer["last_vehicle"]
    else:
        appointment_data[user_id]["vehicle"] = update.message.text

    appointment_data[user_id]["_state"] = "ASKING_SERVICE"

    await update.message.reply_text(
        "Thanks! What type of service do you need?\n\n"
        "Examples:\n"
        "• Oil change\n• Tire rotation\n• Brake inspection\n"
        "• General maintenance\n• Diagnostic/Check engine light\n"
        "• Recall service\n• Other (please describe)"
    )
    return ASKING_SERVICE


async def get_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect service type."""
    user_id = update.effective_user.id
    appointment_data[user_id]["service_type"] = update.message.text
    appointment_data[user_id]["_state"] = "ASKING_DATE"

    await update.message.reply_text(
        "Perfect! What date works best for you?\n"
        "(e.g., 'Tomorrow', 'February 10', 'Next Monday')"
    )
    return ASKING_DATE


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect preferred date."""
    user_id = update.effective_user.id
    appointment_data[user_id]["preferred_date"] = update.message.text
    appointment_data[user_id]["_state"] = "ASKING_TIME"

    await update.message.reply_text(
        "Great! What time would you prefer?\n"
        "(e.g., 'Morning', '10 AM', 'Afternoon', 'Anytime')"
    )
    return ASKING_TIME


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect preferred time and finalize booking."""
    user_id = update.effective_user.id
    appointment_data[user_id]["preferred_time"] = update.message.text

    # Prepare final data (remove internal state field)
    info = {k: v for k, v in appointment_data[user_id].items() if k != "_state"}

    print(f"\n{'=' * 60}")
    print(f"💾 SAVING APPOINTMENT: {info.get('name')} / {info.get('phone')}")
    print(f"{'=' * 60}\n")

    save_appointment(info)
    await notify_advisor(context, info)

    # Confirmation message
    confirmation = (
        "✅ Appointment request received!\n\n📋 Summary:\n"
        f"• Name: {info['name']}\n"
        f"• Phone: {info['phone']}\n"
        f"• Vehicle: {info['vehicle']}\n"
        f"• Service: {info['service_type']}\n"
        f"• Date: {info['preferred_date']}\n"
        f"• Time: {info['preferred_time']}\n"
    )
    if info.get("is_returning"):
        confirmation += f"\n👋 Thanks for coming back! (Visit #{info.get('visit_count', 0) + 1})"
    confirmation += "\n\n🔔 Your service advisor will confirm your appointment shortly!"
    confirmation += "\n\nIs there anything else I can help you with?"

    await update.message.reply_text(confirmation)
    del appointment_data[user_id]
    return ConversationHandler.END


async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel appointment booking."""
    user_id = update.effective_user.id
    appointment_data.pop(user_id, None)
    await update.message.reply_text(
        "❌ Appointment booking cancelled.\n\n"
        "Type 'book appointment' anytime you're ready to schedule!"
    )
    return ConversationHandler.END


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ERROR HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles errors."""
    print(f"❌ Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, I encountered an error. Please try again or contact service directly."
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    """Start the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found in .env!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler for appointment flow
    appointment_handler = ConversationHandler(
        entry_points=[],
        states={
            CONFIRM_IDENTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_identity)],
            ASKING_PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), get_phone)],
            ASKING_VEHICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vehicle)],
            ASKING_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_service)],
            ASKING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            ASKING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel_appointment)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_appointment))
    app.add_handler(appointment_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
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
    print(f"📅 Smart appointment scheduling: ENABLED")
    print(f"🔄 Returning customer detection: ENABLED")
    if ADVISOR_TELEGRAM_ID:
        print(f"📧 Advisor notifications: ENABLED (ID: {ADVISOR_TELEGRAM_ID})")
    else:
        print("⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)")
    print(f"\nPress Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
