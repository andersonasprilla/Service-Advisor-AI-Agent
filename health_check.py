import os
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings

# Load Keys
load_dotenv()

# Setup
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("honda-agent")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# CONFIGURATION
# We will search for a very simple term that MUST be in the manual
TEST_QUERY = "oil"
NAMESPACE = "civic-2025"

print(f"🩺 CONTACTING PINECONE (Namespace: {NAMESPACE})...")

# Get Stats first
stats = index.describe_index_stats()
print(f"📊 Database Stats: {stats}")

# Run a test search
vector = embeddings.embed_query(TEST_QUERY)
results = index.query(
    vector=vector,
    top_k=3,
    include_metadata=True,
    namespace=NAMESPACE
)

print(f"\n🔎 SEARCH RESULTS FOR '{TEST_QUERY}':")
if not results['matches']:
    print("❌ ZERO MATCHES FOUND. The database is empty or the namespace is wrong.")
else:
    for match in results['matches']:
        print(f"✅ Found Score: {match['score']:.2f}")
        # Print the first 100 letters of the text to prove it's real
        text = match['metadata'].get('text', 'NO TEXT')
        print(f"   Content: {text[:100]}...")