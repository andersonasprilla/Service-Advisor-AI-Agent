"""
Rick Case Honda AI Bot — Telegram Entry Point

Message flow:
  1. Auth check
  2. Appointment state machine (if mid-flow)
  3. Orchestrator classifies message in ONE call → {intent, vehicle, escalation}
  4. Dispatch to the right agent/handler

All business logic lives in agents/ and services/.
"""

import re
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler,
)

from config import TELEGRAM_BOT_TOKEN, SHOP_PASSWORD, ADVISOR_TELEGRAM_ID
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
user_sessions = {}          # vehicle namespace per user (for follow-up tech questions)
appointment_data = {}       # partial appointment info during booking


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMAND HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command, including QR code scans."""
    user_id = update.effective_user.id
    is_scan = len(context.args) > 0 and context.args[0] == "scan"

    if is_scan:
        greeting = "Hey! 👋 I'm Anderson's assistant over at Rick Case Honda."
    else:
        greeting = "Hey there! 👋 Welcome to Rick Case Honda."

    if user_id not in allowed_users:
        await update.message.reply_text(
            f"{greeting}\n\n"
            "Quick thing — what's the shop code? Just need it to pull up our system for you."
        )
    else:
        await update.message.reply_text(
            f"{greeting}\n\n"
            "Good to see you again! What's going on with your car today?"
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
        "If you've been here before, I'll probably recognize your number "
        "so we can skip the back-and-forth. 👍"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN MESSAGE HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all incoming text messages through the Orchestrator."""
    user_id = update.effective_user.id
    user_text = update.message.text

    print(f"📩 Received from {user_id} (@{update.effective_user.username}): {user_text}")

    if not ADVISOR_TELEGRAM_ID:
        print(f"💡 TIP: Set ADVISOR_TELEGRAM_ID={user_id} in .env to receive notifications!")

    # ── 1. Check if mid-appointment flow (skip orchestrator) ──
    if user_id in appointment_data and "_state" in appointment_data[user_id]:
        return await _route_appointment_state(update, context)

    # ── 2. Auth check (skip orchestrator) ──
    if user_id not in allowed_users:
        if user_text.strip().upper() == SHOP_PASSWORD:
            allowed_users.append(user_id)
            await update.message.reply_text(
                "You're all set! 👍\n\n"
                "What's going on with your car today?"
            )
        else:
            await update.message.reply_text(
                "I'd love to help! Just need the shop code first so I can pull everything up for you."
            )
        return

    # ── 3. Orchestrator: ONE call to classify everything ──
    decision = orchestrator.classify(user_text)
    intent = decision["intent"]
    vehicle = decision["vehicle"]

    print(f"🎯 Orchestrator: intent={intent} | vehicle={vehicle} | summary={decision['summary']}")

    # ── 4. Dispatch based on intent ──

    # ESCALATION
    if intent == "escalation":
        await update.message.reply_text(
            "I hear you — let me get a real person on this. "
            "I've flagged it for one of our advisors and someone will reach out to you shortly."
        )
        return

    # BOOKING
    if intent == "booking":
        return await start_appointment(update, context)

    # VEHICLE SELECT
    if intent == "vehicle_select" and vehicle:
        user_sessions[user_id] = vehicle
        vehicle_name = vehicle.split("-")[0].title()
        await update.message.reply_text(
            f"{vehicle_name}, got it! What do you need to know?"
        )
        return

    # GREETING
    if intent == "greeting":
        await update.message.reply_text(
            "Hey! 👋 What can I help you with today? "
            "I can look up stuff from your owner's manual or help you schedule a service visit."
        )
        return

    # TECH — the default path
    if vehicle:
        user_sessions[user_id] = vehicle
    target_car = vehicle or user_sessions.get(user_id)

    if target_car:
        print(f"🔎 Searching manual: namespace={target_car}")
        answer = tech_agent.run(user_text, namespace=target_car)

        if "NO_ANSWER_FOUND" in answer:
            await update.message.reply_text(
                "Hmm, I couldn't find that one in the manual. "
                "Want me to set up a time for you to come in and talk to one of our techs?"
            )
        else:
            await update.message.reply_text(answer)
    else:
        await update.message.reply_text(
            "Sure thing — which Honda are we talking about? Civic, Ridgeline, or Passport?"
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
        "Let's get you scheduled! "
        "Can you share your phone number? You can tap the button below or just type it in.",
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
        phone = orchestrator.extract_phone(update.message.text)

    if not phone:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(text="📲 Share My Phone Number", request_contact=True)]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )
        await update.message.reply_text(
            "I didn't catch a phone number there — try tapping the button below or type it out like 954-243-1238.",
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
            f"Hey {customer['name'].title()}! Good to see you back. "
            f"Last time you brought in your {customer['last_vehicle']} — same car this time?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASKING_VEHICLE

    appointment_data[user_id]["phone"] = phone
    appointment_data[user_id]["is_returning"] = False
    appointment_data[user_id]["_state"] = "CONFIRM_IDENTITY"

    await update.message.reply_text(
        "Got it! I don't think we've met — what's your name?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CONFIRM_IDENTITY


async def confirm_identity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect customer name (new customers only)."""
    user_id = update.effective_user.id
    appointment_data[user_id]["name"] = update.message.text.strip()
    appointment_data[user_id]["is_returning"] = False
    appointment_data[user_id]["_state"] = "ASKING_VEHICLE"

    name = update.message.text.strip().split()[0].title()
    await update.message.reply_text(
        f"Nice to meet you, {name}! What car are you bringing in?"
    )
    return ASKING_VEHICLE


async def get_vehicle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect vehicle information."""
    user_id = update.effective_user.id
    user_text = update.message.text.strip().lower()

    if appointment_data[user_id].get("is_returning") and user_text in ["yes", "yeah", "yep", "correct", "same", "yea", "ya", "si"]:
        customer = customer_db.search_by_phone(appointment_data[user_id]["phone"])
        appointment_data[user_id]["vehicle"] = customer["last_vehicle"]
    else:
        appointment_data[user_id]["vehicle"] = update.message.text

    appointment_data[user_id]["_state"] = "ASKING_SERVICE"

    await update.message.reply_text(
        "Got it. What do you need done? Oil change, brakes, check engine light, recall — just let me know."
    )
    return ASKING_SERVICE


async def get_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect service type."""
    user_id = update.effective_user.id
    appointment_data[user_id]["service_type"] = update.message.text
    appointment_data[user_id]["_state"] = "ASKING_DATE"

    await update.message.reply_text(
        "When works best for you? You can say something like \"tomorrow\" or \"next Monday\" — whatever's easiest."
    )
    return ASKING_DATE


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect preferred date."""
    user_id = update.effective_user.id
    appointment_data[user_id]["preferred_date"] = update.message.text
    appointment_data[user_id]["_state"] = "ASKING_TIME"

    await update.message.reply_text(
        "And what time? Morning, afternoon, or a specific time?"
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

    # Confirmation — keep it conversational
    name = info["name"].split()[0].title() if info.get("name") else "there"

    confirmation = (
        f"Perfect, {name} — you're all set! Here's what I've got:\n\n"
        f"🚗 {info['vehicle']}\n"
        f"🔧 {info['service_type']}\n"
        f"📅 {info['preferred_date']} — {info['preferred_time']}\n"
    )

    if info.get("is_returning"):
        confirmation += f"\nGlad to have you back! (Visit #{info.get('visit_count', 0) + 1})"

    confirmation += (
        "\n\nYour advisor will confirm everything shortly. "
        "Anything else I can help with?"
    )

    await update.message.reply_text(confirmation)
    del appointment_data[user_id]
    return ConversationHandler.END


async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel appointment booking."""
    user_id = update.effective_user.id
    appointment_data.pop(user_id, None)
    await update.message.reply_text(
        "No worries, I cancelled that. Just let me know whenever you're ready to reschedule."
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
            "Sorry about that — something went wrong on my end. Try again, "
            "or you can always call us directly at the service desk."
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
    print(f"🧠 Orchestrator: ENABLED (single-call routing)")
    if ADVISOR_TELEGRAM_ID:
        print(f"📧 Advisor notifications: ENABLED (ID: {ADVISOR_TELEGRAM_ID})")
    else:
        print("⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)")
    print(f"\nPress Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
