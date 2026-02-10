"""
Message Handler — Main router for all text messages.

Flow:
  1. Rate limit + block check
  2. Mid-booking check
  3. Pending booking affirmative check
  4. Onboarding check (phone / VIN)
  5. Orchestrator classifies intent
  6. Dispatch to handler
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import ADVISOR_TELEGRAM_ID
from services.session import (
    user_sessions, appointment_data, blocked_users,
    get_or_init_session, check_rate_limit,
    ONBOARD_AWAITING_PHONE, ONBOARD_AWAITING_VIN,
)
from services.customer_db import get_customer_vehicles
from agents.tech_agent import tech_agent
from agents.orchestrator_agent import orchestrator
from handlers.onboarding import handle_onboarding_phone, handle_onboarding_vin
from handlers.booking import start_appointment, handle_booking_message


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all incoming text messages."""
    user_id = update.effective_user.id
    user_text = update.message.text

    print(f"📩 Received from {user_id} (@{update.effective_user.username}): {user_text}")

    if not ADVISOR_TELEGRAM_ID:
        print(f"💡 TIP: Set ADVISOR_TELEGRAM_ID={user_id} in .env to receive notifications!")

    # ── 0. Block + rate limit check ──
    if user_id in blocked_users:
        return

    if not check_rate_limit(user_id):
        await update.message.reply_text(
            "Hey, slow down a bit! You're sending messages too fast. Try again in a minute."
        )
        return

    # ── 1. Mid-booking conversation ──
    handled = await handle_booking_message(update, context)
    if handled:
        return

    # ── 1.5. Pending booking affirmative ──
    session = get_or_init_session(user_id)

    if session.get("pending_booking"):
        affirmatives = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "let's do it",
            "please", "yea", "ya", "si", "absolutely", "for sure",
            "sounds good", "let's go", "do it", "set it up", "book it",
        ]
        if user_text.strip().lower() in affirmatives:
            session["pending_booking"] = False
            print(f"   📅 Caught pending booking affirmative: '{user_text}'")
            return await start_appointment(update, context)
        else:
            session["pending_booking"] = False

    # ── 2. Onboarding check ──
    if session.get("onboarding") == ONBOARD_AWAITING_PHONE:
        handled = await handle_onboarding_phone(update, session)
        if handled:
            return

    if session.get("onboarding") == ONBOARD_AWAITING_VIN:
        handled = await handle_onboarding_vin(update, context, session)
        if handled:
            return

    # If session still needs onboarding (edge case: bot restart)
    if not session.get("phone"):
        session["onboarding"] = ONBOARD_AWAITING_PHONE
        await update.message.reply_text(
            "Hey! Looks like I need to set you up. What's your phone number?"
        )
        return

    # ── 3. Orchestrator: ONE call to classify everything ──
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

    # ── 4. Dispatch ──

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

        if session.get("phone"):
            vehicles = get_customer_vehicles(session["phone"])
            for v in vehicles:
                if v["manual_namespace"] == vehicle:
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

    # TECH — default path
    if vehicle:
        session["namespace"] = vehicle

    target_namespace = session.get("namespace")
    carfax_namespace = session.get("carfax_namespace")

    # Check if asking what vehicle is selected
    vehicle_ask_keywords = [
        "what vehicle", "what car", "which vehicle", "which car",
        "what am i looking at", "what's selected", "which model",
    ]
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
