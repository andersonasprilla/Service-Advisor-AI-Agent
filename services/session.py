"""
Session State — Shared in-memory state for all handlers.

This is the single source of truth for:
  - user_sessions: per-user vehicle, language, history, onboarding state
  - appointment_data: partial appointment info during booking
  - blocked_users: advisor-blocked Telegram IDs
  - rate_limit: per-user message timestamps for spam protection
"""

import re
import time
from services.customer_db import lookup_by_telegram_id, get_customer_vehicles

# ─── Constants ────────────────────────────────────────────────────
ONBOARD_NONE = "none"
ONBOARD_AWAITING_PHONE = "phone"
ONBOARD_AWAITING_VIN = "vin"

RATE_LIMIT_MAX = 10          # Max messages per window
RATE_LIMIT_WINDOW = 60       # Window in seconds

# ─── Shared State ─────────────────────────────────────────────────
user_sessions: dict = {}
appointment_data: dict = {}
blocked_users: list[int] = []
_rate_limit: dict[int, list[float]] = {}


# ─── Session Helpers ──────────────────────────────────────────────

def init_session(user_id: int) -> dict:
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


def load_session_from_profile(user_id: int, customer: dict) -> dict:
    """Build a session dict from a DB customer profile."""
    session = init_session(user_id)

    session["phone"] = customer["phone"]
    session["customer_name"] = customer["name"]

    if customer["vehicles"]:
        primary = next(
            (v for v in customer["vehicles"] if v["is_primary"]),
            customer["vehicles"][0],
        )
        session["namespace"] = primary["manual_namespace"] or "civic-2025"
        session["carfax_namespace"] = (
            primary["carfax_namespace"]
            if primary.get("carfax_status") == "ingested"
            else None
        )
        session["vin"] = primary["vin"]
        session["vehicle_label"] = f"{primary['year']} {primary['make']} {primary['model']}".strip()

        print(f"   🔑 Loaded profile: {session['vehicle_label']} (VIN: {primary['vin'][:8]}...)")
        if session["carfax_namespace"]:
            print(f"   📋 Carfax available: {session['carfax_namespace']}")

    session["onboarding"] = ONBOARD_NONE
    return session


def get_or_init_session(user_id: int) -> dict:
    """
    Get an existing session, load from DB, or create a new one.
    Returns (session, needs_onboarding).
    """
    if user_id in user_sessions:
        session = user_sessions[user_id]
        # Legacy fix: if session was stored as a plain string
        if isinstance(session, str):
            session = init_session(user_id)
            session["namespace"] = "civic-2025"
            user_sessions[user_id] = session
        return session

    # Try to load from DB
    customer = lookup_by_telegram_id(user_id)
    if customer and customer["vehicles"]:
        session = load_session_from_profile(user_id, customer)
        user_sessions[user_id] = session
        return session

    # Brand new — needs onboarding
    session = init_session(user_id)
    session["onboarding"] = ONBOARD_AWAITING_PHONE
    user_sessions[user_id] = session
    return session


def refresh_session_carfax(vin: str):
    """
    After a Carfax is ingested, update any active session
    so the namespace is immediately available.
    """
    for uid, session in user_sessions.items():
        if isinstance(session, dict) and session.get("vin") == vin:
            session["carfax_namespace"] = f"carfax-{vin}"
            print(f"   🔄 Live session updated for user {uid} — Carfax now active")
            break


# ─── Extraction Helpers ───────────────────────────────────────────

def extract_phone(text: str) -> str | None:
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


def extract_vin(text: str) -> str | None:
    """Try to extract a 17-character VIN from text."""
    match = re.search(r'\b[A-HJ-NPR-Z0-9]{17}\b', text.strip().upper())
    return match.group() if match else None


# ─── Rate Limiting ────────────────────────────────────────────────

def check_rate_limit(user_id: int) -> bool:
    """
    Returns True if the user is within rate limits.
    Returns False if they should be throttled.
    """
    now = time.time()

    if user_id not in _rate_limit:
        _rate_limit[user_id] = []

    # Remove timestamps outside the window
    _rate_limit[user_id] = [
        ts for ts in _rate_limit[user_id]
        if now - ts < RATE_LIMIT_WINDOW
    ]

    if len(_rate_limit[user_id]) >= RATE_LIMIT_MAX:
        return False

    _rate_limit[user_id].append(now)
    return True
