"""
Appointment Service — Handles saving appointments and notifying the advisor.
"""

import os
import json
from datetime import datetime
from config import APPOINTMENTS_FILE, ADVISOR_TELEGRAM_ID


def save_appointment(appointment_info: dict):
    """Save appointment to a JSON file (backup/audit trail)."""
    try:
        appointments = []
        if os.path.exists(APPOINTMENTS_FILE):
            with open(APPOINTMENTS_FILE, "r") as f:
                appointments = json.load(f)

        appointment_info["created_at"] = datetime.now().isoformat()
        appointments.append(appointment_info)

        with open(APPOINTMENTS_FILE, "w") as f:
            json.dump(appointments, f, indent=2)

        print(f"✅ Appointment saved ({len(appointments)} total)")

    except Exception as e:
        print(f"❌ Error saving appointment: {e}")
        print(f"📋 Data: {json.dumps(appointment_info, indent=2)}")


async def notify_advisor(bot_context, appointment_info: dict):
    """Send appointment notification to the service advisor via Telegram."""
    if not ADVISOR_TELEGRAM_ID:
        print("⚠️  ADVISOR_TELEGRAM_ID not set — skipping notification.")
        print(f"📋 Appointment: {json.dumps(appointment_info, indent=2)}")
        return

    returning = "🔄 RETURNING" if appointment_info.get("is_returning") else "🆕 NEW"

    message = (
        f"🔔 {returning} APPOINTMENT REQUEST\n\n"
        f"👤 Customer: {appointment_info['name']}\n"
        f"📞 Phone: {appointment_info['phone']}\n"
        f"🚗 Vehicle: {appointment_info['vehicle']}\n"
        f"🔧 Service: {appointment_info['service_type']}\n"
        f"📅 Preferred Date: {appointment_info['preferred_date']}\n"
        f"⏰ Preferred Time: {appointment_info['preferred_time']}\n"
    )

    if appointment_info.get("is_returning"):
        message += f"\n📊 Visit History: {appointment_info.get('visit_count', 0)} previous visits"
        if appointment_info.get("all_vehicles"):
            message += f"\n🚙 Previous Vehicles: {', '.join(appointment_info['all_vehicles'])}"
        message += f"\n🔧 Last Service: {appointment_info.get('last_service', 'N/A')}"

    message += f"\n\n💬 Telegram: @{appointment_info.get('telegram_username', 'N/A')}"
    message += f"\n🆔 User ID: {appointment_info['user_id']}"
    message += "\n\n⚡ Action Required: Add to CDK/DMS manually"

    try:
        await bot_context.bot.send_message(chat_id=ADVISOR_TELEGRAM_ID, text=message)
        print(f"✅ Notification sent to advisor (ID: {ADVISOR_TELEGRAM_ID})")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}")
