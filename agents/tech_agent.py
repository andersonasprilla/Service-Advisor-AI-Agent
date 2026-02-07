"""
TechAgent — Answers technical questions using RAG from Honda manuals.

Context comes from Pinecone vector search against the vehicle manual.
"""

from agents.base_agent import BaseAgent
from services.clients import get_embeddings, get_pinecone_index
from config import RAG_TOP_K


class TechAgent(BaseAgent):

    system_prompt_template = """You are a Honda Technical Assistant at Rick Case Honda.
Answer the customer's question based ONLY on the following context from the manual.
If the answer is NOT in the context, reply exactly with: "NO_ANSWER_FOUND"

Keep your answer concise and helpful. Use bullet points for clarity when appropriate.

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

        return "\n---\n".join(chunks)


# Convenience singleton
tech_agent = TechAgent()
