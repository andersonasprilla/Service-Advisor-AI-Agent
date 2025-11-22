import os
from dotenv import load_dotenv
from pinecone import Pinecone

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("honda-agent")

# This deletes ONLY the specific folder, not the whole database
print("🗑️ Deleting the bad '2024-civic' namespace...")
index.delete(delete_all=True, namespace="2024-civic")
print("✅ Done. The drawer is empty.")