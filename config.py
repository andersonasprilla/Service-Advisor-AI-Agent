"""
Centralized configuration and shared clients.
All API keys, constants, and reusable clients live here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys & Secrets ───────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "honda-agent")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SHOP_PASSWORD = os.getenv("SHOP_PASSWORD", "HONDA2025")
ADVISOR_TELEGRAM_ID = os.getenv("ADVISOR_TELEGRAM_ID")

if ADVISOR_TELEGRAM_ID:
    ADVISOR_TELEGRAM_ID = int(ADVISOR_TELEGRAM_ID)

# ─── Model Settings ───────────────────────────────────────────────
LLM_MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "text-embedding-3-small"
RAG_TOP_K = 15

# ─── Vehicle Namespace Mapping ────────────────────────────────────
VEHICLE_NAMESPACES = {
    "passport": "passport-2026",
    "civic": "civic-2025",
    "ridgeline": "ridgeline-2025",
}

# ─── Data Paths ───────────────────────────────────────────────────
DATA_FOLDER = "./data"
APPOINTMENTS_FILE = "appointments.json"
