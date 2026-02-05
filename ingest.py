import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone

# 1. Load environment variables
load_dotenv()

def ingest_manual(pdf_path, namespace):
    """
    Ingest a PDF manual into Pinecone with specified namespace
    
    Args:
        pdf_path: Path to the PDF file
        namespace: Namespace to store the data (e.g., 'civic-2025')
    """
    # --- CONFIGURATION ---
    index_name = os.getenv("PINECONE_INDEX_NAME")
    
    if not index_name:
        print("❌ Error: PINECONE_INDEX_NAME is missing from .env")
        return False

    # 2. Initialize Pinecone
    try:
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        index = pc.Index(index_name)
        print(f"✅ Connected to Pinecone index: {index_name}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False

    print(f"\n🚀 Starting ingestion")
    print(f"📂 File: {pdf_path}")
    print(f"📁 Namespace: {namespace}")
    print("-" * 50)

    # 3. Load the PDF
    if not os.path.exists(pdf_path):
        print(f"❌ Error: Could not find '{pdf_path}'")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Available files: {os.listdir('.')}")
        return False

    print(f"📚 Loading {pdf_path}...")
    try:
        loader = PyPDFLoader(pdf_path)
        raw_docs = loader.load()
        print(f"   ✅ Loaded {len(raw_docs)} pages")
    except Exception as e:
        print(f"   ❌ Error loading PDF: {e}")
        return False

    # 4. Split the text
    print("✂️  Splitting text into chunks...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    documents = text_splitter.split_documents(raw_docs)
    print(f"   ✅ Created {len(documents)} text chunks")

    # 5. Embed and Upsert to Pinecone
    print("🧠 Embedding and uploading (this may take a few minutes)...")
    
    # Ensure this matches your Pinecone Index Dimensions (1536 for OpenAI)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # Process in batches
    batch_size = 100
    total_uploaded = 0
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        
        vectors = []
        for doc in batch:
            # Create the vector (List of floats)
            vector_values = embeddings.embed_query(doc.page_content)
            
            # Create ID and Metadata
            chunk_id = f"{namespace}-{i + batch.index(doc)}"
            metadata = {
                "text": doc.page_content,
                "page": doc.metadata.get("page", 0),
                "source": pdf_path,
                "namespace": namespace
            }
            
            vectors.append({
                "id": chunk_id,
                "values": vector_values,
                "metadata": metadata
            })
        
        # Upload!
        try:
            index.upsert(vectors=vectors, namespace=namespace)
            total_uploaded += len(batch)
            print(f"   ✅ Uploaded batch {i // batch_size + 1}: {total_uploaded}/{len(documents)} chunks")
        except Exception as e:
            print(f"   ❌ Error uploading batch: {e}")
            return False

    print(f"\n🎉 Ingestion Complete!")
    print(f"✅ Successfully uploaded {total_uploaded} chunks to namespace '{namespace}'")
    return True

def ingest_all_manuals():
    """Ingest all available Honda manuals"""
    manuals = [
        ("civic_2025_manual.pdf", "civic-2025"),
        ("ridgeline_2025_manual.pdf", "ridgeline-2025"),
        ("passport_2026_manual.pdf", "passport-2026"),
    ]
    
    print("\n" + "="*60)
    print("HONDA MANUALS INGESTION")
    print("="*60 + "\n")
    
    results = []
    for pdf_path, namespace in manuals:
        if os.path.exists(pdf_path):
            success = ingest_manual(pdf_path, namespace)
            results.append((pdf_path, namespace, success))
            print()  # Empty line between manuals
        else:
            print(f"⚠️  Skipping {pdf_path} (file not found)")
            results.append((pdf_path, namespace, False))
    
    # Summary
    print("\n" + "="*60)
    print("INGESTION SUMMARY")
    print("="*60)
    for pdf_path, namespace, success in results:
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{status}: {pdf_path} → {namespace}")
    print("="*60 + "\n")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Single file mode: python ingest.py civic_2025_manual.pdf civic-2025
        if len(sys.argv) == 3:
            pdf_path = sys.argv[1]
            namespace = sys.argv[2]
            ingest_manual(pdf_path, namespace)
        else:
            print("Usage: python ingest.py <pdf_path> <namespace>")
            print("Example: python ingest.py civic_2025_manual.pdf civic-2025")
            print("\nOr run without arguments to ingest all manuals")
    else:
        # Batch mode: ingest all available manuals
        ingest_all_manuals()
