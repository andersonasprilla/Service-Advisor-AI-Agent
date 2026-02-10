"""
Photo Handler — Analyze customer-uploaded images using GPT-4o vision.

Handles:
  - Recall letters / mail from Honda
  - Dashboard warning lights
  - Error codes on screen
  - Tire damage, dents, fluid leaks
  - Registration / documents
  - Anything visual the customer wants to ask about

Flow:
  1. Customer sends photo (with optional caption)
  2. Bot downloads the image
  3. GPT-4o vision analyzes it with vehicle context
  4. Bot responds naturally
  5. If visit is recommended → triggers pending_booking
"""

import base64
from telegram import Update
from telegram.ext import ContextTypes

from config import ADVISOR_TELEGRAM_ID
from services.session import (
    user_sessions, get_or_init_session, blocked_users, check_rate_limit,
    ONBOARD_AWAITING_PHONE, ONBOARD_AWAITING_VIN,
)
from services.clients import get_llm


PHOTO_SYSTEM_PROMPT = """You're a service advisor at Rick Case Honda, texting with a customer who just sent you a photo.

LANGUAGE: Respond in {language}. Be natural — text like a native speaker.

CUSTOMER VEHICLE: {vehicle_context}

Analyze the image and respond helpfully. Common scenarios:
- RECALL LETTER: Read it, summarize what the recall is about, which component is affected, urgency level, and whether they need to come in. If it's a safety recall, strongly recommend scheduling service.
- WARNING LIGHT: Identify the light, explain what it means, and whether it's urgent or informational.
- DAMAGE PHOTO: Describe what you see, give your honest assessment, and recommend coming in if needed.
- ERROR CODE: Read the code, explain what it means in plain language.
- DOCUMENT: Read and summarize the relevant info.
- OTHER: Do your best to help with whatever they sent.

Style rules:
- Sound human. Short, warm, no fluff.
- NO numbered lists, NO bullet points, NO bold text. Just talk naturally.
- Never say "based on the image" or "I can see in the photo" — just say it like you're looking at it in person.
- Keep it to 3-5 sentences max.
- If the image is unclear or you can't tell what it is, just ask them to describe what they're looking at.

VISIT RECOMMENDATION:
- Safety recalls, warning lights, damage, leaks, strange noises → suggest they come in
- Informational only (tire pressure reading, feature question, document summary) → just answer

After your response, on a NEW LINE, add one of these tags (the customer won't see this):
- [VISIT:YES] if you recommended bringing the car in
- [VISIT:NO] if it was just an info answer"""


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads from customers."""
    user_id = update.effective_user.id
    caption = update.message.caption or ""

    print(f"📸 Photo received from {user_id} (@{update.effective_user.username})")
    if caption:
        print(f"   Caption: {caption}")

    # Block + rate limit
    if user_id in blocked_users:
        return

    if not check_rate_limit(user_id):
        await update.message.reply_text(
            "Hey, slow down a bit! Try again in a minute."
        )
        return

    # Get session
    session = get_or_init_session(user_id)

    # If still onboarding, nudge them to finish setup first
    if session.get("onboarding") in (ONBOARD_AWAITING_PHONE, ONBOARD_AWAITING_VIN):
        if session["onboarding"] == ONBOARD_AWAITING_PHONE:
            await update.message.reply_text(
                "I'd love to take a look at that! But first, let me get you set up — "
                "what's your phone number?"
            )
        else:
            await update.message.reply_text(
                "I'll check that out for you! Just need your VIN first so I can pull up your vehicle. "
                "It's 17 characters — on your windshield or registration."
            )
        return

    # Download the photo
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Get the highest resolution version
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = await file.download_as_bytearray()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        print(f"   📥 Downloaded photo: {len(image_bytes)} bytes")
    except Exception as e:
        print(f"   ❌ Photo download failed: {e}")
        await update.message.reply_text(
            "I couldn't load that image — could you try sending it again?"
        )
        return

    # Build context
    lang = session.get("language", "en")
    lang_names = {
        "en": "English", "es": "Spanish", "pt": "Portuguese",
        "fr": "French", "ht": "Haitian Creole", "zh": "Chinese",
    }
    lang_label = lang_names.get(lang, lang)

    vehicle_context = "Unknown vehicle"
    if session.get("vehicle_label"):
        vehicle_context = session["vehicle_label"]
        if session.get("vin"):
            vehicle_context += f" (VIN: ...{session['vin'][-6:]})"

    system_content = PHOTO_SYSTEM_PROMPT.format(
        language=lang_label,
        vehicle_context=vehicle_context,
    )

    # Build the user message with image
    user_content = []
    user_content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
    })

    if caption:
        user_content.append({"type": "text", "text": caption})
    else:
        user_content.append({"type": "text", "text": "What's this? Can you help me with this?"})

    # Call GPT-4o with vision
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        # Use gpt-4o for vision (gpt-4o-mini also supports it)
        vision_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]

        result = vision_llm.invoke(messages)
        response = result.content

        print(f"   ✅ Vision analysis complete")
    except Exception as e:
        print(f"   ❌ Vision analysis failed: {e}")
        await update.message.reply_text(
            "I had trouble analyzing that image. Could you describe what you're looking at? "
            "Or try sending a clearer photo."
        )
        return

    # Parse visit recommendation
    suggests_visit = "[VISIT:YES]" in response
    clean_response = response.replace("[VISIT:YES]", "").replace("[VISIT:NO]", "").strip()

    await update.message.reply_text(clean_response)

    # Update session
    session["pending_booking"] = suggests_visit
    if suggests_visit:
        print(f"   📅 Photo analysis suggested a visit — pending_booking ON")

    # Add to conversation history
    session["history"].append(f"User: [sent a photo] {caption}")
    session["history"].append(f"Assistant: {clean_response}")

    if len(session["history"]) > 6:
        session["history"] = session["history"][-6:]
