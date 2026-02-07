"""
Health check — verify Pinecone connection and test a search.

Usage:
  python health_check.py                  # Test default namespace (civic-2025)
  python health_check.py passport-2026    # Test a specific namespace
"""

import sys
from services.clients import get_embeddings, get_pinecone_index

TEST_QUERY = "oil"
NAMESPACE = sys.argv[1] if len(sys.argv) > 1 else "civic-2025"

index = get_pinecone_index()
embeddings = get_embeddings()

print(f"\n🩺 HEALTH CHECK — namespace: '{NAMESPACE}'")
print("=" * 50)

# Stats
stats = index.describe_index_stats()
print(f"📊 Index stats: {stats}\n")

# Test search
vector = embeddings.embed_query(TEST_QUERY)
results = index.query(
    vector=vector,
    top_k=3,
    include_metadata=True,
    namespace=NAMESPACE,
)

print(f"🔎 Search results for '{TEST_QUERY}':")
if not results["matches"]:
    print("❌ ZERO MATCHES. Namespace may be empty or wrong.")
else:
    for match in results["matches"]:
        text = match["metadata"].get("text", "NO TEXT")
        print(f"  ✅ Score: {match['score']:.2f} — {text[:100]}...")

print()
