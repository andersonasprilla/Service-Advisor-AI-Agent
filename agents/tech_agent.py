"""
TechAgent — Adaptive RAG with Contextual Memory + Carfax Support.

1. Rewrites user query based on Conversation History.
2. Fast Search (Standard) -> Returns if Score > 0.65.
3. Smart Search (Expansion) -> If Fast Search fails.
4. Carfax Search -> Also searches carfax-{VIN} namespace if available.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from agents.base_agent import BaseAgent
from services.clients import get_embeddings, get_pinecone_index, get_llm
from config import RAG_TOP_K


class TechAgent(BaseAgent):

    system_prompt_template = """You're a service advisor at Rick Case Honda, texting a customer.
Talk like a real person — the way you'd text a friend who asked about their car. Short, warm, no fluff.

LANGUAGE: Respond in {language}. Match the customer's language naturally. If Spanish, text like a native Spanish speaker (casual, not formal). Same for any language — be natural, not robotic or overly translated.

Answer based ONLY on the context below (owner's manual + vehicle history if available). If the answer isn't there, reply exactly: "NO_ANSWER_FOUND"

Style rules:
- Sound human. Use casual language, contractions, slang appropriate for the language.
- NO numbered lists, NO bullet points, NO bold text. Just talk naturally in short sentences.
- Never say "according to the manual" or "based on the context" or "based on the Carfax" — just say it like you know it.
- Keep it to 2-4 sentences max. Don't over-explain.
- Never start with "Great question" or "That's a good question" (or equivalents in other languages).

CARFAX / VEHICLE HISTORY:
- If the customer asks about accidents, damage, recalls, warranty, service history, previous owners, or odometer — use the Carfax context below.
- Present Carfax info confidently: "Your car is clean — no accidents, one owner, 690 miles" not "The Carfax report shows..."
- For warranty questions, give specific remaining coverage if available.

VISIT RECOMMENDATION — Use your judgment:
- If the issue NEEDS professional attention (warning lights, strange noises, leaks, safety concerns, error codes, something broken, maintenance due), suggest they bring the car in.
- If it's just an INFO question (tire pressure specs, how to pair bluetooth, warranty status, vehicle history), just answer it helpfully. No need to suggest a visit.

After your response, on a NEW LINE, add one of these tags (the customer won't see this):
- [VISIT:YES] if you recommended bringing the car in
- [VISIT:NO] if it was just an info answer

<manual_context>
{context}
</manual_context>

<carfax_context>
{carfax_context}
</carfax_context>"""

    def __init__(self):
        super().__init__(name="TechAgent")

    def contextualize_query(self, history: list, latest_query: str) -> str:
        """
        Uses LLM to rewrite 'reset it' into 'reset the tire pressure light'
        based on the last few messages.
        """
        if not history:
            return latest_query
        
        print(f"   🧠 {self.name}: Contextualizing query...")
        llm = get_llm()
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Given a chat history and the latest user question which might reference context in the chat history, formulate a standalone question which can be understood without the chat history. Do NOT answer the question, just reformulate it if needed and otherwise return it as is."),
            ("human", "Chat History:\n{history}\n\nLatest Question: {input}")
        ])
        
        chain = prompt | llm | StrOutputParser()
        try:
            history_str = "\n".join(history)
            reformulated = chain.invoke({"history": history_str, "input": latest_query})
            print(f"   🔄 Reformulated: '{latest_query}' -> '{reformulated}'")
            return reformulated
        except Exception as e:
            print(f"   ⚠️ Contextualize failed: {e}")
            return latest_query

    def generate_search_queries(self, user_text: str, namespace: str) -> list[str]:
        """Generate 3 search-optimized variations."""
        print(f"   🧠 {self.name}: Brainstorming search terms...")
        
        llm = get_llm()
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert Honda technician. Generate 3 distinct, keyword-rich search queries to find the answer to the user's problem in the vehicle owner's manual. Focus on technical terminology. Return ONLY the 3 queries separated by newlines."),
            ("human", "Vehicle: {vehicle}\nUser Problem: {input}"),
        ])
        
        chain = prompt | llm | StrOutputParser()
        
        try:
            response = chain.invoke({"vehicle": namespace, "input": user_text})
            queries = [q.strip() for q in response.split('\n') if q.strip()]
            return queries[:3]
        except Exception as e:
            print(f"   ⚠️ {self.name}: Query expansion failed ({e}). Using original only.")
            return []

    def _search_namespace(self, query: str, namespace: str, top_k: int = 5) -> list[dict]:
        """Search a single Pinecone namespace and return matches."""
        embeddings = get_embeddings()
        index = get_pinecone_index()

        query_vector = embeddings.embed_query(query)
        results = index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
        )
        return results.get("matches", [])

    def _search_carfax(self, search_query: str, carfax_namespace: str) -> str:
        """
        Search the Carfax namespace for vehicle history info.
        Returns context string or empty string if no carfax data.
        """
        if not carfax_namespace:
            return "No vehicle history data available for this customer yet."

        print(f"   📋 {self.name}: Searching Carfax namespace: {carfax_namespace}")

        try:
            matches = self._search_namespace(search_query, carfax_namespace, top_k=5)

            if not matches:
                print(f"   ⚠️ No Carfax data found in {carfax_namespace}")
                return "No vehicle history data available for this customer yet."

            best_score = matches[0]["score"] if matches else 0
            print(f"   📋 Carfax best match: {best_score:.4f}")

            # Lower threshold for Carfax — it's a smaller, more focused dataset
            if best_score < 0.40:
                return "No relevant vehicle history found for this question."

            chunks = [m["metadata"]["text"] for m in matches]
            return "\n---\n".join(chunks)

        except Exception as e:
            print(f"   ⚠️ Carfax search failed: {e}")
            return "Vehicle history search unavailable."

    def build_context(self, user_message: str, **kwargs) -> str:
        """
        1. Contextualize (Rewrite) Query
        2. Fast Search in manual namespace
        3. Adaptive Expansion if needed
        
        Note: Carfax search is handled separately in run() since it goes
        into a different prompt placeholder.
        """
        namespace = kwargs.get("namespace", "civic-2025")
        history = kwargs.get("history", [])

        embeddings = get_embeddings()
        index = get_pinecone_index()

        # 🧠 STEP 0: CONTEXTUALIZE
        search_query = self.contextualize_query(history, user_message)

        # 🚀 STEP 1: FAST SEARCH (manual only)
        print(f"   ⚡ {self.name}: Trying fast search for: '{search_query}'")
        initial_results = self._search_namespace(search_query, namespace, top_k=5)
        
        best_initial_score = 0.0
        if initial_results:
            best_initial_score = initial_results[0]["score"]
        
        if best_initial_score > 0.65:
            print(f"   ✅ Fast match found (Score: {best_initial_score:.4f}). Skipping expansion.")
            chunks = [m["metadata"]["text"] for m in initial_results]
            return "\n---\n".join(chunks)

        # 🐢 STEP 2: SMART SEARCH (Fallback)
        print(f"   ⚠️ Match weak ({best_initial_score:.4f}). Engaging Query Expansion...")
        
        variations = self.generate_search_queries(search_query, namespace)
        search_queries = [search_query] + variations
        
        unique_matches = {}

        for query in search_queries:
            matches = self._search_namespace(query, namespace, top_k=5)
            for match in matches:
                if match["id"] not in unique_matches or match["score"] > unique_matches[match["id"]]["score"]:
                    unique_matches[match["id"]] = match

        final_matches = sorted(unique_matches.values(), key=lambda x: x["score"], reverse=True)[:RAG_TOP_K]

        if not final_matches:
            return "NO_ANSWER_FOUND"

        top_score = final_matches[0]["score"]
        print(f"      📊 Final Best Match Score: {top_score:.4f}")

        if top_score < 0.50:
            print(f"      ⛔ Score {top_score:.4f} is too low. Blocking LLM.")
            return "NO_ANSWER_FOUND"

        chunks = [m["metadata"]["text"] for m in final_matches]
        return "\n---\n".join(chunks)

    def run(self, user_message: str, **kwargs) -> str:
        """
        Override BaseAgent.run() to inject {language} and {carfax_context}.
        """
        language = kwargs.get("language", "en")
        carfax_namespace = kwargs.get("carfax_namespace", None)
        
        lang_names = {
            "en": "English", "es": "Spanish", "pt": "Portuguese",
            "fr": "French", "ht": "Haitian Creole", "zh": "Chinese",
            "ko": "Korean", "vi": "Vietnamese", "ja": "Japanese",
        }
        lang_label = lang_names.get(language, language)

        print(f"   🤖 {self.name}: Processing (lang={lang_label}, carfax={'YES' if carfax_namespace else 'NO'})...")

        try:
            # Build manual context (existing RAG flow)
            manual_context = self.build_context(user_message, **kwargs)

            # Build carfax context (new — searches carfax namespace)
            # Contextualize the query first for better carfax search
            history = kwargs.get("history", [])
            search_query = self.contextualize_query(history, user_message) if history else user_message
            carfax_context = self._search_carfax(search_query, carfax_namespace)

            # If manual has nothing but carfax does, don't bail out
            if manual_context == "NO_ANSWER_FOUND" and "No " in carfax_context[:5]:
                # Neither source has anything
                return "NO_ANSWER_FOUND"

            # Build the final prompt with both contexts
            system_content = self.system_prompt_template.format(
                context=manual_context if manual_context != "NO_ANSWER_FOUND" else "No manual information found for this question.",
                carfax_context=carfax_context,
                language=lang_label,
            )

            from services.clients import get_llm
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_content),
                ("human", "{input}"),
            ])
            chain = prompt | llm | StrOutputParser()
            response = chain.invoke({"input": user_message})

            print(f"   ✅ {self.name}: Done")
            return response

        except Exception as e:
            print(f"   ❌ {self.name} Error: {e}")
            return (
                f"I encountered an error while processing your request. "
                f"Please try again or contact service directly."
            )

# Singleton
tech_agent = TechAgent()
