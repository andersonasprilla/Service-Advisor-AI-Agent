import os
from openai import OpenAI
from pinecone import Pinecone

# 1. Initialize Clients (Standard, no LangChain needed)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

# Connect to your index
index_name = os.getenv("PINECONE_INDEX_NAME", "honda-agent")
index = pc.Index(index_name)

TECH_SYSTEM_PROMPT = """
You are a Honda Technical Assistant.
Answer the user's question based ONLY on the following context from the manual.
If the answer is not in the context, say "I couldn't find that in the manual."

Keep your answer concise and helpful. Use bullet points for clarity when appropriate.

<context>
{context}
</context>
"""

def run_tech_agent(user_message, namespace="civic-2025"):
    """
    Run the technical agent with RAG (Retrieval Augmented Generation)
    
    Args:
        user_message: The user's question
        namespace: The Pinecone namespace to search (e.g., 'civic-2025', 'passport-2026')
    
    Returns:
        AI-generated answer based on manual context
    """
    print(f"   🔧 Tech Agent: Processing question for namespace '{namespace}'...")
    
    try:
        # A. Create Embedding (Turn text into numbers)
        # Make sure to use the same model you used to upload the data!
        print("   🔧 Tech Agent: Generating embedding...")
        emb_response = client.embeddings.create(
            input=user_message,
            model="text-embedding-3-small" 
        )
        query_vector = emb_response.data[0].embedding
        
        # B. Search Pinecone
        print(f"   🔧 Tech Agent: Searching Pinecone namespace '{namespace}'...")
        search_results = index.query(
            vector=query_vector,
            top_k=5,
            include_metadata=True,
            namespace=namespace
        )
        
        # Check if we got results
        if not search_results['matches']:
            return f"I couldn't find any information in the {namespace} manual. This might be a different vehicle or the data hasn't been uploaded yet."
        
        # C. Extract the text from the matches
        contexts = []
        for match in search_results['matches']:
            if 'text' in match['metadata']:
                contexts.append(match['metadata']['text'])
        
        if not contexts:
            return "I found some results but couldn't extract the information. Please try rephrasing your question."
        
        combined_context = "\n\n".join(contexts)
        
        # D. Ask GPT-4
        print("   🔧 Tech Agent: Asking GPT-4...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": TECH_SYSTEM_PROMPT.format(context=combined_context)},
                {"role": "user", "content": user_message}
            ],
            temperature=0
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"   ❌ Tech Agent Error: {e}")
        return f"I encountered an error: {str(e)}. Please try again or contact service directly."

# --- TESTING FUNCTION ---
def test_tech_agent():
    """Test the tech agent with sample questions"""
    print("\n" + "="*50)
    print("TESTING TECH AGENT")
    print("="*50 + "\n")
    
    test_cases = [
        ("What's the oil capacity for the Civic?", "civic-2025"),
        ("How do I check tire pressure?", "civic-2025"),
        ("What does the maintenance minder A17 mean?", "civic-2025"),
    ]
    
    for question, namespace in test_cases:
        print(f"\n📝 Question: {question}")
        print(f"📂 Namespace: {namespace}")
        print("-" * 50)
        answer = run_tech_agent(question, namespace)
        print(f"💬 Answer: {answer}\n")

if __name__ == "__main__":
    test_tech_agent()
