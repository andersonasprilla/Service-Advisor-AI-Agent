"""
Reset a Pinecone namespace (e.g., delete bad data from a wrong upload).

Usage:
  python reset_db.py                    # Deletes default '2024-civic' namespace
  python reset_db.py civic-2025         # Deletes a specific namespace
"""

import sys
from config import PINECONE_INDEX_NAME
from services.clients import get_pinecone_index

index = get_pinecone_index()

namespace = sys.argv[1] if len(sys.argv) > 1 else "2024-civic"

print(f"🗑️ Deleting namespace '{namespace}' from index '{PINECONE_INDEX_NAME}'...")
index.delete(delete_all=True, namespace=namespace)
print(f"✅ Done. Namespace '{namespace}' is now empty.")
