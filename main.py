import os
from dotenv import load_dotenv
from fastapi import FastAPI, Form
from twilio.twiml.messaging_response import MessagingResponse

from pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

app = FastAPI()

# --- SETUP ---
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
pinecone_index = pc.Index("honda-agent")
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# --- MEMORY STORAGE (The "Guest List") ---
# Stores the car model for each phone number
user_sessions = {}

# --- THE ROUTER ---
def identify_vehicle(user_text: str):
    """
    Determines if the user MENTIONED a car in this specific message.
    Updates: Matches the specific namespaces in your Pinecone screenshot.
    """
    system_prompt = """
    You are a router for a Honda AI. 
    Analyze the user's question and identify if they explicitly mention a car model.
    
    - If they mention a Passport, return: passport-2026
    - If they mention a Civic, return: civic-2025
    - If they mention a Ridgeline, return: ridgeline-2025
    - If they do NOT mention a car, return: unknown
    
    Return ONLY the string.
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{text}")
    ])
    
    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"text": user_text})
    return result.strip().lower()

# --- THE SEARCH ---
def get_answer_from_manual(question: str, namespace: str):
    print(f"🔎 Searching in drawer: [{namespace}] for: {question}")
    
    query_vector = embeddings.embed_query(question)
    
    # UPGRADE 1: Increase top_k to 15 to find pages deep in the section
    search_results = pinecone_index.query(
        vector=query_vector,
        top_k=15, 
        include_metadata=True,
        namespace=namespace
    )
    
    context_text = ""
    for match in search_results['matches']:
        # UPGRADE 2: Print the page numbers it found (X-Ray Vision)
        page_num = match['metadata'].get('page', 'Unknown')
        print(f"   - Found info on Page {page_num}")
        
        context_text += match['metadata']['text'] + "\n---\n"
        
    prompt_template = ChatPromptTemplate.from_template("""
    You are a helpful Honda Service Advisor Assistant.
    Answer the customer's question ONLY based on the following manual context.
    If the answer is not in the context, say "I'm sorry, I couldn't find that in the manual."
    Keep the answer friendly but concise (suitable for SMS).
    
    Context from Manual:
    {context}
    
    Customer Question:
    {question}
    """)
    
    chain = prompt_template | llm
    response = chain.invoke({
        "context": context_text, 
        "question": question
    })
    
    return response.content

@app.get("/")
async def health_check():
    return {"message": "Honda Memory Agent is awake!"}

@app.post("/sms")
async def reply_to_sms(Body: str = Form(...), From: str = Form(...)):
    print(f"📩 Received from {From}: {Body}")
    
    # 1. Check if the user explicitly named a car in this message
    detected_car = identify_vehicle(Body)
    
    # 2. Logic: Determine which car to use
    target_car = None
    
    if detected_car != "unknown":
        # Case A: User said the car name (e.g., "My Ridgeline...")
        target_car = detected_car
        # Save it to memory!
        user_sessions[From] = target_car
        print(f"💾 Saved new car for {From}: {target_car}")
        
    else:
        # Case B: User didn't say a name, check memory
        if From in user_sessions:
            target_car = user_sessions[From]
            print(f"🧠 Remembered car for {From}: {target_car}")
        else:
            target_car = None

    resp = MessagingResponse()

    # 3. Action
    if target_car:
        # We have a car -> Answer the question
        ai_answer = get_answer_from_manual(Body, target_car)
        resp.message(ai_answer)
    else:
        # We still don't know the car -> Ask the user
        print("🤷 Unknown car. Asking user.")
        resp.message("I can help with that! Which vehicle is this for? (Passport, Civic, or Ridgeline?)")
    
    return str(resp)