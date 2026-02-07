"""
Ingest Honda PDF manuals into Pinecone.

Usage:
  python ingest.py                                    # Ingest all available manuals
  python ingest.py civic_2025_manual.pdf civic-2025   # Ingest a single manual
"""

import os
import sys
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import PINECONE_INDEX_NAME, EMBEDDING_MODEL
from services.clients import get_embeddings, get_pinecone_index

load_dotenv()


def ingest_manual(pdf_path: str, namespace: str) -> bool:
    """Ingest a single PDF manual into Pinecone."""
    if not os.path.exists(pdf_path):
        print(f"❌ File not found: {pdf_path}")
        return False

    print(f"\n🚀 Ingesting: {pdf_path} → namespace '{namespace}'")
    print("-" * 50)

    # Load PDF
    loader = PyPDFLoader(pdf_path)
    raw_docs = loader.load()
    print(f"   ✅ Loaded {len(raw_docs)} pages")

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    documents = splitter.split_documents(raw_docs)
    print(f"   ✅ Created {len(documents)} text chunks")

    # Embed and upload
    embeddings = get_embeddings()
    index = get_pinecone_index()
    batch_size = 100
    total = 0

    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        vectors = []

        for j, doc in enumerate(batch):
            vector_values = embeddings.embed_query(doc.page_content)
            vectors.append({
                "id": f"{namespace}-{i + j}",
                "values": vector_values,
                "metadata": {
                    "text": doc.page_content,
                    "page": doc.metadata.get("page", 0),
                    "source": pdf_path,
                    "namespace": namespace,
                },
            })

        index.upsert(vectors=vectors, namespace=namespace)
        total += len(batch)
        print(f"   ✅ Uploaded {total}/{len(documents)} chunks")

    print(f"\n🎉 Done! {total} chunks → '{namespace}'")
    return True


def ingest_all_manuals():
    """Ingest all available Honda manuals."""
    manuals = [
        ("civic_2025_manual.pdf", "civic-2025"),
        ("ridgeline_2025_manual.pdf", "ridgeline-2025"),
        ("passport_2026_manual.pdf", "passport-2026"),
    ]

    print("\n" + "=" * 60)
    print("HONDA MANUALS INGESTION")
    print("=" * 60 + "\n")

    results = []
    for pdf_path, namespace in manuals:
        if os.path.exists(pdf_path):
            success = ingest_manual(pdf_path, namespace)
            results.append((pdf_path, namespace, success))
        else:
            print(f"⚠️  Skipping {pdf_path} (not found)")
            results.append((pdf_path, namespace, False))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for pdf_path, namespace, success in results:
        status = "✅" if success else "❌"
        print(f"  {status} {pdf_path} → {namespace}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        ingest_manual(sys.argv[1], sys.argv[2])
    else:
        ingest_all_manuals()
