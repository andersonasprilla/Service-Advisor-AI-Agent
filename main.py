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
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler,
)

from config import TELEGRAM_BOT_TOKEN, SHOP_PASSWORD, ADVISOR_TELEGRAM_ID
from utils.data_setup import setup_data_folder
from services.customer_database import customer_db
from services.appointments import save_appointment, notify_advisor
from services.customer_db import (
    lookup_by_telegram_id, get_customer_vehicles,
    get_primary_vehicle, set_primary_vehicle,
)
from agents.tech_agent import tech_agent
from agents.orchestrator_agent import orchestrator

# ─── Startup ──────────────────────────────────────────────────────
setup_data_folder()

# ─── Conversation States (legacy — booking is now conversational) ──
# Kept for ConversationHandler compatibility if needed
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

    # ── 1. Check if mid-booking conversation (skip orchestrator) ──
    if user_id in appointment_data:
        # Handle /cancel
        if user_text.strip().lower() in ["/cancel", "cancel", "cancelar", "nevermind"]:
            del appointment_data[user_id]
            cancel_msgs = {
                "es": "Sin problema, lo cancelé. Avísame cuando quieras reagendar.",
                "pt": "Sem problema, cancelei. Me avisa quando quiser reagendar.",
            }
            session_lang = user_sessions.get(user_id, {}).get("language", "en")
            msg = cancel_msgs.get(session_lang, "No worries, I cancelled that. Just let me know whenever you're ready to reschedule.")
            await update.message.reply_text(msg)
            return

        # Continue the booking conversation
        from agents.booking_agent import booking_agent
        session_data = user_sessions.get(user_id, {})
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        reply, is_complete = booking_agent.run(user_text, appointment_data[user_id], session_data)
        
        await update.message.reply_text(reply)

        if is_complete:
            # Save and notify
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
        
        return

    # ── 1.5 Check if user is responding "yes" to a booking offer ──
    if user_id in user_sessions and isinstance(user_sessions[user_id], dict):
        if user_sessions[user_id].get("pending_booking"):
            affirmatives = ["yes", "yeah", "yep", "sure", "ok", "okay", "let's do it",
                            "please", "yea", "ya", "si", "absolutely", "for sure",
                            "sounds good", "let's go", "do it", "set it up", "book it"]
            if user_text.strip().lower() in affirmatives:
                user_sessions[user_id]["pending_booking"] = False
                print(f"   📅 Caught pending booking affirmative: '{user_text}'")
                return await start_appointment(update, context)
            else:
                # They said something else — clear the flag and continue normally
                user_sessions[user_id]["pending_booking"] = False

    # ── 2. Auth check (case-insensitive password) ──
    if user_id not in allowed_users:
        if user_text.strip().upper() == SHOP_PASSWORD.upper():
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

    # ── 3. Session Management (VIN-aware) ──
    if user_id not in user_sessions:
        # Try to load customer profile from DB (by telegram_id)
        customer = lookup_by_telegram_id(user_id)
        if customer and customer["vehicles"]:
            primary = next((v for v in customer["vehicles"] if v["is_primary"]), customer["vehicles"][0])
            user_sessions[user_id] = {
                "namespace": primary["manual_namespace"] or "civic-2025",
                "carfax_namespace": primary["carfax_namespace"],
                "vin": primary["vin"],
                "vehicle_label": f"{primary['year']} {primary['make']} {primary['model']}".strip(),
                "phone": customer["phone"],
                "customer_name": customer["name"],
                "language": "en",
                "history": [],
                "pending_booking": False,
            }
            print(f"   🔑 Loaded profile: {user_sessions[user_id]['vehicle_label']} (VIN: {primary['vin'][:8]}...)")
        else:
            user_sessions[user_id] = {
                "namespace": "civic-2025",
                "carfax_namespace": None,
                "vin": None,
                "vehicle_label": None,
                "phone": None,
                "customer_name": None,
                "language": "en",
                "history": [],
                "pending_booking": False,
            }

    # Legacy fix: if session was stored as a plain string, convert to dict
    if isinstance(user_sessions[user_id], str):
        user_sessions[user_id] = {
            "namespace": user_sessions[user_id],
            "carfax_namespace": None,
            "vin": None,
            "vehicle_label": None,
            "phone": None,
            "customer_name": None,
            "language": "en",
            "history": [],
            "pending_booking": False,
        }

    session = user_sessions[user_id]

    # ── 4. Orchestrator: ONE call to classify everything ──
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    decision = orchestrator.classify(user_text)
    intent = decision["intent"]
    vehicle = decision["vehicle"]

    # Update session language (only if orchestrator detected one — fast path returns None)
    detected_lang = decision.get("language")
    if detected_lang:
        session["language"] = detected_lang
    lang = session.get("language", "en")

    print(f"🎯 Orchestrator: intent={intent} | vehicle={vehicle} | lang={lang} | summary={decision['summary']}")

    # ── 5. Dispatch based on intent ──

    # ESCALATION
    if intent == "escalation" or decision.get("escalation"):
        escalation_msgs = {
            "es": "Entendido — déjame conectarte con un asesor. Alguien te escribirá pronto.",
            "pt": "Entendi — vou te conectar com um consultor. Alguém vai entrar em contato em breve.",
        }
        msg = escalation_msgs.get(lang,
            "I hear you — let me get a real person on this. "
            "I've flagged it for one of our advisors and someone will reach out to you shortly."
        )
        await update.message.reply_text(msg)
        return

    # BOOKING
    if intent == "booking":
        return await start_appointment(update, context)

    # VEHICLE SELECT
    if intent == "vehicle_select" and vehicle:
        session["namespace"] = vehicle
        session["history"] = []  # Clear history so we don't mix up cars
        session["carfax_namespace"] = None  # Reset carfax until we know the VIN
        session["vin"] = None
        vehicle_name = vehicle.split("-")[0].title()
        
        # If customer has vehicles in DB, try to match and load Carfax namespace
        if session.get("phone"):
            vehicles = get_customer_vehicles(session["phone"])
            for v in vehicles:
                if v["manual_namespace"] == vehicle:
                    session["carfax_namespace"] = v["carfax_namespace"]
                    session["vin"] = v["vin"]
                    session["vehicle_label"] = f"{v['year']} {v['make']} {v['model']}".strip()
                    break
        
        await update.message.reply_text(
            f"{vehicle_name}, got it! What do you need to know?"
        )
        return

    # GREETING
    if intent == "greeting":
        greeting_msgs = {
            "es": "¡Hola! 👋 ¿En qué te puedo ayudar hoy? "
                  "Puedo buscar info en el manual de tu vehículo o ayudarte a agendar una cita de servicio.",
            "pt": "Oi! 👋 Como posso te ajudar hoje? "
                  "Posso buscar informações no manual do seu veículo ou ajudar a agendar um serviço.",
        }
        msg = greeting_msgs.get(lang,
            "Hey! 👋 What can I help you with today? "
            "I can look up stuff from your owner's manual or help you schedule a service visit."
        )
        await update.message.reply_text(msg)
        return

    # OFF TOPIC
    if intent == "off_topic":
        offtopic_msgs = {
            "es": "Soy solo un bot de autos — no puedo ayudar con eso! 😅 "
                  "Pero si tienes preguntas sobre tu Honda, con gusto te ayudo.",
            "pt": "Sou apenas um bot de carros — não posso ajudar com isso! 😅 "
                  "Mas se tiver perguntas sobre seu Honda, é só falar.",
        }
        msg = offtopic_msgs.get(lang,
            "I'm just a car bot — I can't really help with that! 😅 "
            "But if you have questions about your Honda, let me know."
        )
        await update.message.reply_text(msg)
        return

    # TECH — the default path
    if vehicle:
        session["namespace"] = vehicle

    target_namespace = session["namespace"]

    # Check if the user is asking what vehicle is selected (don't waste a RAG call)
    vehicle_ask_keywords = ["what vehicle", "what car", "which vehicle", "which car",
                            "what am i looking at", "what's selected", "which model"]
    if any(kw in user_text.lower() for kw in vehicle_ask_keywords):
        if session.get("vehicle_label"):
            msg = f"You're set up on your {session['vehicle_label']} right now."
            if session.get("vin"):
                msg += f" (VIN: ...{session['vin'][-6:]})"
            msg += " Want to switch? Just say Civic, Ridgeline, or Passport."
            await update.message.reply_text(msg)
        elif target_namespace:
            vehicle_name = target_namespace.split("-")[0].title()
            await update.message.reply_text(
                f"You're set up on the {vehicle_name} right now. Want to switch? "
                f"Just say Civic, Ridgeline, or Passport."
            )
        else:
            await update.message.reply_text(
                "No vehicle selected yet — which Honda are we talking about? Civic, Ridgeline, or Passport?"
            )
        return

    if target_namespace:
        print(f"🔎 Searching manual: namespace={target_namespace} | lang={lang}")
        answer = tech_agent.run(
            user_text,
            namespace=target_namespace,
            history=session["history"],
            language=lang,
        )

        if "NO_ANSWER_FOUND" in answer:
            no_answer_msgs = {
                "es": "Hmm, no encontré eso en el manual. "
                      "¿Quieres que te agende una cita para que lo revise un técnico?",
                "pt": "Hmm, não encontrei isso no manual. "
                      "Quer que eu agende uma visita para um técnico dar uma olhada?",
            }
            msg = no_answer_msgs.get(lang,
                "Hmm, I couldn't find that one in the manual. "
                "Want me to set up a time for you to come in and talk to one of our techs?"
            )
            await update.message.reply_text(msg)
            session["pending_booking"] = True
        else:
            # Parse the [VISIT:YES/NO] tag from the agent's response
            suggests_visit = "[VISIT:YES]" in answer
            # Strip the tag before sending to customer
            clean_answer = answer.replace("[VISIT:YES]", "").replace("[VISIT:NO]", "").strip()
            
            await update.message.reply_text(clean_answer)
            session["pending_booking"] = suggests_visit
            
            if suggests_visit:
                print(f"   📅 Tech agent suggested a visit — pending_booking ON")
            else:
                print(f"   ℹ️ Info-only answer — no booking nudge")

        # Update conversation memory (use clean answer without tags)
        clean = answer.replace("[VISIT:YES]", "").replace("[VISIT:NO]", "").strip()
        session["history"].append(f"User: {user_text}")
        session["history"].append(f"Assistant: {clean}")

        # Keep memory efficient (last 6 turns / 3 exchanges)
        if len(session["history"]) > 6:
            session["history"] = session["history"][-6:]
    else:
        await update.message.reply_text(
            "Sure thing — which Honda are we talking about? Civic, Ridgeline, or Passport?"
        )


async def _route_appointment_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy — no longer used. Booking is now conversational."""
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPOINTMENT — CONVERSATIONAL BOOKING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a conversational booking flow."""
    user_id = update.effective_user.id
    user_text = update.message.text
    session = user_sessions.get(user_id, {})
    lang = session.get("language", "en")

    # Initialize appointment with whatever we already know from the session
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

    # Let the booking agent handle the first message naturally
    from agents.booking_agent import booking_agent

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply, is_complete = booking_agent.run(user_text, appointment_data[user_id], session)

    await update.message.reply_text(reply)

    if is_complete:
        info = {k: v for k, v in appointment_data[user_id].items()
                if k not in ("_state", "messages")}
        info["user_id"] = user_id
        info["telegram_username"] = update.effective_user.username

        save_appointment(info)
        await notify_advisor(context, info)
        del appointment_data[user_id]


async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel appointment booking."""
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

    # All message routing goes through handle_message (including booking)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_appointment))
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
