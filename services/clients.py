"""
Shared client singletons.
Initialized once, imported everywhere. No duplicate connections.
"""

from config import (
    OPENAI_API_KEY, PINECONE_API_KEY,
    PINECONE_INDEX_NAME, LLM_MODEL, EMBEDDING_MODEL,
)

# ─── Lazy-initialized globals ─────────────────────────────────────
_llm = None
_embeddings = None
_pinecone_index = None


def get_llm():
    """Return a shared ChatOpenAI instance (lazy init)."""
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI
        _llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
        print(f"✅ LLM initialized: {LLM_MODEL}")
    return _llm


def get_embeddings():
    """Return a shared OpenAIEmbeddings instance (lazy init)."""
    global _embeddings
    if _embeddings is None:
        from langchain_openai import OpenAIEmbeddings
        _embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        print(f"✅ Embeddings initialized: {EMBEDDING_MODEL}")
    return _embeddings


def get_pinecone_index():
    """Return a shared Pinecone Index instance (lazy init)."""
    global _pinecone_index
    if _pinecone_index is None:
        from pinecone import Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(PINECONE_INDEX_NAME)
        print(f"✅ Pinecone connected: {PINECONE_INDEX_NAME}")
    return _pinecone_index
