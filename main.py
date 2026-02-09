"""
Rick Case Honda AI Bot — Telegram Entry Point

Message flow:
  1. Auth check (shop password)
  2. Onboarding check (phone → VIN for new customers)
  3. Appointment state machine (if mid-flow)
  4. Orchestrator classifies message → {intent, vehicle, escalation}
  5. Dispatch to the right agent/handler

Advisor flow:
  - Advisor sends a Carfax PDF with VIN in the caption → auto-ingest into Pinecone

All business logic lives in agents/ and services/.
"""

import os
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
    get_or_create_customer, add_vehicle, decode_vin,
    ingest_carfax, update_carfax_status, get_vehicle_by_vin,
)
from agents.tech_agent import tech_agent
from agents.orchestrator_agent import orchestrator

# ─── Startup ──────────────────────────────────────────────────────
setup_data_folder()

# ─── In-Memory State ─────────────────────────────────────────────
allowed_users = []          # Authenticated Telegram user IDs
user_sessions = {}          # Per-user session data (vehicle, language, history, etc.)
appointment_data = {}       # Partial appointment info during booking

# Onboarding states
ONBOARD_NONE = "none"               # Not onboarding
ONBOARD_AWAITING_PHONE = "phone"    # Waiting for phone number
ONBOARD_AWAITING_VIN = "vin"        # Waiting for VIN


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _extract_phone(text: str) -> str | None:
    """Try to extract a 10-digit US phone number from text."""
    patterns = [
        r'\(\d{3}\)\s*\d{3}[-\s]?\d{4}',
        r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',
        r'\b\d{10}\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            digits = re.sub(r'\D', '', match.group())
            if len(digits) == 10:
                return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return None


def _extract_vin(text: str) -> str | None:
    """Try to extract a 17-character VIN from text."""
    # VINs are 17 alphanumeric characters (no I, O, Q)
    match = re.search(r'\b[A-HJ-NPR-Z0-9]{17}\b', text.strip().upper())
    return match.group() if match else None


def _init_session(user_id: int) -> dict:
    """Create a fresh session dict."""
    return {
        "namespace": None,
        "carfax_namespace": None,
        "vin": None,
        "vehicle_label": None,
        "phone": None,
        "customer_name": None,
        "language": "en",
        "history": [],
        "pending_booking": False,
        "onboarding": ONBOARD_NONE,
    }


def _load_session_from_profile(user_id: int, customer: dict) -> dict:
    """Build a session dict from a DB customer profile."""
    session = _init_session(user_id)

    session["phone"] = customer["phone"]
    session["customer_name"] = customer["name"]

    if customer["vehicles"]:
        primary = next(
            (v for v in customer["vehicles"] if v["is_primary"]),
            customer["vehicles"][0],
        )
        session["namespace"] = primary["manual_namespace"] or "civic-2025"
        session["carfax_namespace"] = primary["carfax_namespace"] if primary.get("carfax_status") == "ingested" else None
        session["vin"] = primary["vin"]
        session["vehicle_label"] = f"{primary['year']} {primary['make']} {primary['model']}".strip()

        print(f"   🔑 Loaded profile: {session['vehicle_label']} (VIN: {primary['vin'][:8]}...)")
        if session["carfax_namespace"]:
            print(f"   📋 Carfax available: {session['carfax_namespace']}")

    session["onboarding"] = ONBOARD_NONE
    return session


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
# ONBOARDING HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_onboarding_phone(update: Update, session: dict) -> bool:
    """
    Handle the phone number collection step.
    
    Returns True if we handled the message (caller should return early).
    """
    user_id = update.effective_user.id
    user_text = update.message.text

    phone = _extract_phone(user_text)

    if not phone:
        await update.message.reply_text(
            "Hmm, I couldn't catch a phone number there. "
            "Could you send it like (954) 555-1234 or 9545551234?"
        )
        return True

    print(f"   📞 Onboarding: Got phone {phone}")

    # Check the CSV database (historical records)
    csv_result = customer_db.search_by_phone(phone)

    # Create or update in SQLite
    customer = get_or_create_customer(
        phone=phone,
        name=csv_result["name"] if csv_result else None,
        telegram_id=user_id,
    )

    session["phone"] = phone
    session["customer_name"] = customer["name"]

    if csv_result:
        # Returning customer found in CSV history
        session["customer_name"] = csv_result["name"]
        print(f"   🔄 Returning customer: {csv_result['name']} ({csv_result['visit_count']} visits)")

        await update.message.reply_text(
            f"Hey {csv_result['name'].title()}! 👋 Good to see you again — "
            f"I see you've been in {csv_result['visit_count']} time(s) before.\n\n"
            f"I just need your VIN so I can pull up your vehicle info. "
            f"You can find it on the lower corner of your windshield or on your registration. "
            f"It's 17 characters."
        )
        session["onboarding"] = ONBOARD_AWAITING_VIN
        return True

    # Check if they already have vehicles in SQLite
    if customer["vehicles"]:
        # They're already set up (e.g., added by advisor via CLI)
        session_data = _load_session_from_profile(user_id, customer)
        user_sessions[user_id] = session_data

        veh = customer["vehicles"][0]
        await update.message.reply_text(
            f"Found you! You're set up with your "
            f"{veh['year']} {veh['make']} {veh['model']}. "
            f"What can I help you with today?"
        )
        return True

    # Brand new customer
    await update.message.reply_text(
        f"Got it, thanks! Looks like this is your first time with us.\n\n"
        f"Could you send me your VIN? It's 17 characters — "
        f"you'll find it on the lower corner of your windshield or on your registration."
    )
    session["onboarding"] = ONBOARD_AWAITING_VIN
    return True


async def handle_onboarding_vin(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict) -> bool:
    """
    Handle the VIN collection step.
    Decodes VIN, creates vehicle, notifies advisor for Carfax.
    
    Returns True if we handled the message.
    """
    user_id = update.effective_user.id
    user_text = update.message.text

    vin = _extract_vin(user_text)

    if not vin:
        await update.message.reply_text(
            "That doesn't look like a VIN — they're exactly 17 characters, "
            "letters and numbers only. Could you double-check and try again?"
        )
        return True

    print(f"   🔑 Onboarding: Got VIN {vin[:8]}...")

    # Decode the VIN via NHTSA
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    decoded = decode_vin(vin)

    if not decoded or not decoded.get("model"):
        await update.message.reply_text(
            "Hmm, I couldn't decode that VIN. Could you double-check the number? "
            "Make sure it's the full 17 characters from your windshield or registration."
        )
        return True

    # Add vehicle to the customer's profile
    vehicle = add_vehicle(
        phone=session["phone"],
        vin=vin,
        is_primary=True,
        decoded=decoded,
    )

    if not vehicle:
        await update.message.reply_text(
            "Something went wrong saving your vehicle. Let me flag this for the team."
        )
        return True

    # Update session with the new vehicle
    session["vin"] = vin
    session["namespace"] = decoded["manual_namespace"] or "civic-2025"
    session["carfax_namespace"] = None  # Pending — not ingested yet
    session["vehicle_label"] = f"{decoded['year']} {decoded['make']} {decoded['model']}".strip()
    session["onboarding"] = ONBOARD_NONE  # Onboarding complete!

    vehicle_desc = f"{decoded['year']} {decoded['make']} {decoded['model']}"
    if decoded.get("trim"):
        vehicle_desc += f" {decoded['trim']}"

    # Notify the advisor to pull the Carfax
    await _notify_advisor_carfax_needed(context, session, vin, vehicle_desc, user_id, update.effective_user.username)

    # Welcome the customer
    await update.message.reply_text(
        f"Got it — {vehicle_desc}! 🚗\n\n"
        f"I'm pulling up your vehicle history now — my advisor will have that ready shortly. "
        f"In the meantime, I've got the owner's manual loaded up.\n\n"
        f"What can I help you with?"
    )

    print(f"   ✅ Onboarding complete: {vehicle_desc} (VIN: {vin[:8]}...)")
    return True


async def _notify_advisor_carfax_needed(
    context: ContextTypes.DEFAULT_TYPE,
    session: dict,
    vin: str,
    vehicle_desc: str,
    user_id: int,
    username: str,
):
    """Send the advisor a notification to pull and upload the Carfax."""
    if not ADVISOR_TELEGRAM_ID:
        print(f"   ⚠️ ADVISOR_TELEGRAM_ID not set — can't request Carfax")
        print(f"   📋 Need Carfax for VIN: {vin}")
        return

    message = (
        f"📋 CARFAX NEEDED\n\n"
        f"👤 Customer: {session.get('customer_name') or 'New Customer'}\n"
        f"📞 Phone: {session.get('phone', 'N/A')}\n"
        f"🚗 Vehicle: {vehicle_desc}\n"
        f"🔑 VIN: {vin}\n\n"
        f"💬 Telegram: @{username or 'N/A'}\n"
        f"🆔 User ID: {user_id}\n\n"
        f"📌 Action: Pull the Carfax and send the PDF here.\n"
        f"Just reply with the PDF and put the VIN in the caption:\n"
        f"{vin}"
    )

    try:
        await context.bot.send_message(chat_id=ADVISOR_TELEGRAM_ID, text=message)
        print(f"   ✅ Carfax request sent to advisor")
    except Exception as e:
        print(f"   ❌ Failed to notify advisor: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADVISOR CARFAX PDF HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle document uploads. If it's a PDF from the advisor with a VIN caption,
    ingest it as a Carfax report.
    """
    user_id = update.effective_user.id
    document = update.message.document

    # Only process PDFs
    if not document.file_name.lower().endswith(".pdf"):
        # If it's not the advisor, just ignore
        if ADVISOR_TELEGRAM_ID and user_id == ADVISOR_TELEGRAM_ID:
            await update.message.reply_text("I can only process PDF files. Please send the Carfax as a PDF.")
        return

    # Check if this is from the advisor
    if not ADVISOR_TELEGRAM_ID or user_id != ADVISOR_TELEGRAM_ID:
        await update.message.reply_text(
            "Thanks for the file! Right now I can only process documents sent by the service advisor. "
            "If you need help, just ask me a question about your vehicle."
        )
        return

    # Extract VIN from caption
    caption = update.message.caption or ""
    vin = _extract_vin(caption)

    if not vin:
        # Try the filename too
        vin = _extract_vin(document.file_name)

    if not vin:
        await update.message.reply_text(
            "I need the VIN to know which vehicle this goes with.\n\n"
            "Please resend the PDF with the 17-digit VIN in the caption, like:\n"
            "2HGFE1E57TH472154"
        )
        return

    # Check if vehicle exists in DB
    vehicle = get_vehicle_by_vin(vin)
    if not vehicle:
        await update.message.reply_text(
            f"⚠️ No vehicle found for VIN: {vin}\n"
            f"The customer needs to register first by sending their phone number and VIN to the bot."
        )
        return

    await update.message.reply_text(f"📥 Got it — ingesting Carfax for VIN: {vin[:8]}... This will take a minute.")

    # Download the PDF
    os.makedirs("./data/carfax", exist_ok=True)
    pdf_path = f"./data/carfax/carfax_{vin}.pdf"

    try:
        file = await document.get_file()
        await file.download_to_drive(pdf_path)
        print(f"   📥 Downloaded Carfax PDF: {pdf_path}")
    except Exception as e:
        print(f"   ❌ PDF download failed: {e}")
        await update.message.reply_text(f"❌ Failed to download the PDF: {e}")
        return

    # Ingest into Pinecone
    try:
        success = ingest_carfax(pdf_path, vin)

        if success:
            await update.message.reply_text(
                f"✅ Carfax ingested for VIN: {vin}\n\n"
                f"Vehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}\n"
                f"Namespace: carfax-{vin}\n\n"
                f"The customer can now ask about their vehicle history, "
                f"warranty status, accidents, and more."
            )

            # Update any active session for this vehicle's owner
            _refresh_session_carfax(vehicle, vin)

        else:
            await update.message.reply_text(f"❌ Ingestion failed for VIN: {vin}. Check the logs.")

    except Exception as e:
        print(f"   ❌ Carfax ingestion error: {e}")
        await update.message.reply_text(f"❌ Error during ingestion: {e}")


def _refresh_session_carfax(vehicle: dict, vin: str):
    """
    If the customer is currently online (has an active session),
    update their session so the carfax namespace is immediately available.
    """
    for uid, session in user_sessions.items():
        if isinstance(session, dict) and session.get("vin") == vin:
            session["carfax_namespace"] = f"carfax-{vin}"
            print(f"   🔄 Live session updated for user {uid} — Carfax now active")
            break


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

    # ── 1. Check if mid-booking conversation (skip everything else) ──
    if user_id in appointment_data:
        # Handle /cancel
        if user_text.strip().lower() in ["/cancel", "cancel", "cancelar", "nevermind"]:
            del appointment_data[user_id]
            session_lang = user_sessions.get(user_id, {}).get("language", "en")
            cancel_msgs = {
                "es": "Sin problema, lo cancelé. Avísame cuando quieras reagendar.",
                "pt": "Sem problema, cancelei. Me avisa quando quiser reagendar.",
            }
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
                user_sessions[user_id]["pending_booking"] = False

    # ── 2. Auth check ──
    if user_id not in allowed_users:
        if user_text.strip().upper() == SHOP_PASSWORD.upper():
            allowed_users.append(user_id)

            # Check if we already know this customer
            customer = lookup_by_telegram_id(user_id)
            if customer and customer["vehicles"]:
                # Already registered — load profile and skip onboarding
                user_sessions[user_id] = _load_session_from_profile(user_id, customer)
                veh = customer["vehicles"][0]
                await update.message.reply_text(
                    f"Welcome back! 👋 I've got your {veh['year']} {veh['make']} {veh['model']} loaded up.\n\n"
                    f"What's going on with your car today?"
                )
            else:
                # New user — start onboarding
                session = _init_session(user_id)
                session["onboarding"] = ONBOARD_AWAITING_PHONE
                user_sessions[user_id] = session

                await update.message.reply_text(
                    "You're all set! 👍\n\n"
                    "First things first — what's your phone number? "
                    "I'll use it to pull up your info if you've been here before."
                )
        else:
            await update.message.reply_text(
                "I'd love to help! Just need the shop code first so I can pull everything up for you."
            )
        return

    # ── 3. Onboarding check (phone → VIN for new customers) ──
    if user_id not in user_sessions:
        # Edge case: authenticated but no session (e.g., bot restarted)
        customer = lookup_by_telegram_id(user_id)
        if customer and customer["vehicles"]:
            user_sessions[user_id] = _load_session_from_profile(user_id, customer)
        else:
            session = _init_session(user_id)
            session["onboarding"] = ONBOARD_AWAITING_PHONE
            user_sessions[user_id] = session
            await update.message.reply_text(
                "Hey! Looks like I need to set you up. What's your phone number?"
            )
            return

    # Legacy fix: if session was stored as a plain string, convert
    if isinstance(user_sessions[user_id], str):
        user_sessions[user_id] = _init_session(user_id)
        user_sessions[user_id]["namespace"] = "civic-2025"

    session = user_sessions[user_id]

    # Handle onboarding states
    if session.get("onboarding") == ONBOARD_AWAITING_PHONE:
        handled = await handle_onboarding_phone(update, session)
        if handled:
            return

    if session.get("onboarding") == ONBOARD_AWAITING_VIN:
        handled = await handle_onboarding_vin(update, context, session)
        if handled:
            return

    # ── 4. Orchestrator: ONE call to classify everything ──
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    decision = orchestrator.classify(user_text)
    intent = decision["intent"]
    vehicle = decision["vehicle"]

    # Update session language
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
        session["history"] = []
        session["carfax_namespace"] = None
        session["vin"] = None
        vehicle_name = vehicle.split("-")[0].title()
        
        # If customer has vehicles in DB, try to match and load Carfax namespace
        if session.get("phone"):
            vehicles = get_customer_vehicles(session["phone"])
            for v in vehicles:
                if v["manual_namespace"] == vehicle:
                    # Only set carfax namespace if it's been ingested
                    if v.get("carfax_status") == "ingested":
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

    target_namespace = session.get("namespace")
    carfax_namespace = session.get("carfax_namespace")

    # Check if the user is asking what vehicle is selected
    vehicle_ask_keywords = ["what vehicle", "what car", "which vehicle", "which car",
                            "what am i looking at", "what's selected", "which model"]
    if any(kw in user_text.lower() for kw in vehicle_ask_keywords):
        if session.get("vehicle_label"):
            msg = f"You're set up on your {session['vehicle_label']} right now."
            if session.get("vin"):
                msg += f" (VIN: ...{session['vin'][-6:]})"
            if carfax_namespace:
                msg += " I've got your vehicle history loaded too."
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
        print(f"🔎 Searching: manual={target_namespace} | carfax={carfax_namespace or 'none'} | lang={lang}")
        answer = tech_agent.run(
            user_text,
            namespace=target_namespace,
            carfax_namespace=carfax_namespace,
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
            suggests_visit = "[VISIT:YES]" in answer
            clean_answer = answer.replace("[VISIT:YES]", "").replace("[VISIT:NO]", "").strip()
            
            await update.message.reply_text(clean_answer)
            session["pending_booking"] = suggests_visit

        # Update conversation memory
        clean = answer.replace("[VISIT:YES]", "").replace("[VISIT:NO]", "").strip()
        session["history"].append(f"User: {user_text}")
        session["history"].append(f"Assistant: {clean}")

        if len(session["history"]) > 6:
            session["history"] = session["history"][-6:]
    else:
        await update.message.reply_text(
            "Sure thing — which Honda are we talking about? Civic, Ridgeline, or Passport?"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPOINTMENT — CONVERSATIONAL BOOKING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_appointment))

    # Document handler (Carfax PDF uploads from advisor)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Text message handler (everything else)
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
    print(f"📋 Carfax ingestion: ENABLED (advisor sends PDF → auto-ingest)")
    if ADVISOR_TELEGRAM_ID:
        print(f"📧 Advisor notifications: ENABLED (ID: {ADVISOR_TELEGRAM_ID})")
    else:
        print("⚠️  Advisor notifications: DISABLED (set ADVISOR_TELEGRAM_ID in .env)")
    print(f"\nPress Ctrl+C to stop")
    print(f"{'=' * 50}\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
