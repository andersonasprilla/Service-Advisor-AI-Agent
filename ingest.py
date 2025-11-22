import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone

# 1. Load environment variables (API Keys)
load_dotenv()

# 2. Initialize Pinecone
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index_name = "honda-agent"  # Make sure this matches your Pinecone index name
index = pc.Index(index_name)

def ingest_manual():
    print("🚀 Starting ingestion...")

    # 3. Load the PDF
    # CHANGE THIS to match your actual PDF filename
    pdf_path = "civic_2025_manual.pdf" 
    
    if not os.path.exists(pdf_path):
        print(f"❌ Error: Could not find {pdf_path}. Did you download it?")
        return

    print(f"📚 Loading {pdf_path}...")
    loader = PyPDFLoader(pdf_path)
    raw_docs = loader.load()
    print(f"   Loaded {len(raw_docs)} pages.")

    # 4. Split the text
    # We split into chunks of 1000 characters with a little overlap
    # so we don't cut sentences in half.
    print("✂️  Splitting text...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    documents = text_splitter.split_documents(raw_docs)
    print(f"   Created {len(documents)} text chunks.")

    # 5. Embed and Upsert to Pinecone
    print("🧠 Embedding and uploading to Pinecone (this may take a minute)...")
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # We process in batches of 100 to avoid hitting API limits
    batch_size = 100
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        
        # Create vectors
        vectors = []
        for doc in batch:
            # Turn text into numbers
            vector_values = embeddings.embed_query(doc.page_content)
            
            # Create a unique ID for this chunk (e.g., "page-5-chunk-2")
            chunk_id = f"id-{i + batch.index(doc)}"
            
            # Metadata is the text we will read back later
            metadata = {
                "text": doc.page_content,
                "page": doc.metadata.get("page", 0)
            }
            
            vectors.append({
                "id": chunk_id,
                "values": vector_values,
                "metadata": metadata
            })
        
        # Upload to the 'model-year' namespace
        index.upsert(vectors=vectors, namespace="civic-2025")
        print(f"   Uploaded batch {i} to {i + len(batch)}")

    print("✅ Ingestion Complete! The manual is now in the Brain.")

if __name__ == "__main__":
    ingest_manual()