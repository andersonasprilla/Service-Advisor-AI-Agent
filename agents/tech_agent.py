"""
TechAgent — Answers technical questions using RAG from Honda manuals.

Context comes from Pinecone vector search against the vehicle manual.
"""

from agents.base_agent import BaseAgent
from services.clients import get_embeddings, get_pinecone_index
from config import RAG_TOP_K


class TechAgent(BaseAgent):

    system_prompt_template = """You are a friendly service advisor assistant at Rick Case Honda.
You're texting with a customer — keep it natural and conversational, like a helpful coworker.

Answer based ONLY on the manual context below. If the answer isn't there, reply exactly: "NO_ANSWER_FOUND"

Guidelines:
- Talk like a real person, not a robot. Short sentences. Casual but professional.
- Skip the formalities — no "Dear customer" or "Thank you for your inquiry".
- If there are steps, keep them simple and numbered.
- Don't say "according to the manual" — just give the answer naturally.
- It's okay to say "looks like" or "from what I can see" to keep it human.

<context>
{context}
</context>"""

    def __init__(self):
        super().__init__(name="TechAgent")

    def build_context(self, user_message: str, **kwargs) -> str:
        """Search Pinecone for relevant manual chunks."""
        namespace = kwargs.get("namespace", "civic-2025")
        print(f"   🔧 {self.name}: Searching namespace '{namespace}'...")

        embeddings = get_embeddings()
        index = get_pinecone_index()

        # Embed the question
        query_vector = embeddings.embed_query(user_message)

        # Search Pinecone
        results = index.query(
            vector=query_vector,
            top_k=RAG_TOP_K,
            include_metadata=True,
            namespace=namespace,
        )

        if not results["matches"]:
            return "No relevant information found in the manual."

        # Extract text chunks
        chunks = [
            match["metadata"]["text"]
            for match in results["matches"]
            if "text" in match.get("metadata", {})
        ]
        
        # Inside build_context method...
        chunks = []
        for match in results["matches"]:
            text = match["metadata"]["text"]
            page = match["metadata"].get("page", "??")
            print(f"      📄 Found evidence on Page {page}") # <--- ADD THIS DEBUG LINE
            chunks.append(text)

        return "\n---\n".join(chunks)
        


# Convenience singleton
tech_agent = TechAgent()
