"""
Onboarding Handlers — Phone → VIN collection for new customers.
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import ADVISOR_TELEGRAM_ID
from services.session import (
    user_sessions, extract_phone, extract_vin,
    load_session_from_profile,
    ONBOARD_NONE, ONBOARD_AWAITING_VIN,
)
from services.customer_db import (
    get_or_create_customer, add_vehicle, decode_vin,
    get_customer_vehicles,
)
from services.customer_database import customer_db


async def handle_onboarding_phone(update: Update, session: dict) -> bool:
    """
    Handle the phone number collection step.
    Returns True if we handled the message (caller should return early).
    """
    user_id = update.effective_user.id
    user_text = update.message.text

    phone = extract_phone(user_text)

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
        session_data = load_session_from_profile(user_id, customer)
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

    vin = extract_vin(user_text)

    if not vin:
        await update.message.reply_text(
            "That doesn't look like a VIN — they're exactly 17 characters, "
            "letters and numbers only. Could you double-check and try again?"
        )
        return True

    print(f"   🔑 Onboarding: Got VIN {vin[:8]}...")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    decoded = decode_vin(vin)

    if not decoded or not decoded.get("model"):
        await update.message.reply_text(
            "Hmm, I couldn't decode that VIN. Could you double-check the number? "
            "Make sure it's the full 17 characters from your windshield or registration."
        )
        return True

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

    # Update session
    session["vin"] = vin
    session["namespace"] = decoded["manual_namespace"] or "civic-2025"
    session["carfax_namespace"] = None
    session["vehicle_label"] = f"{decoded['year']} {decoded['make']} {decoded['model']}".strip()
    session["onboarding"] = ONBOARD_NONE

    vehicle_desc = f"{decoded['year']} {decoded['make']} {decoded['model']}"
    if decoded.get("trim"):
        vehicle_desc += f" {decoded['trim']}"

    # Notify advisor to pull Carfax
    await notify_advisor_carfax_needed(context, session, vin, vehicle_desc, user_id, update.effective_user.username)

    await update.message.reply_text(
        f"Got it — {vehicle_desc}! 🚗\n\n"
        f"I'm pulling up your vehicle history now — my advisor will have that ready shortly. "
        f"In the meantime, I've got the owner's manual loaded up.\n\n"
        f"What can I help you with?"
    )

    print(f"   ✅ Onboarding complete: {vehicle_desc} (VIN: {vin[:8]}...)")
    return True


async def notify_advisor_carfax_needed(
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
