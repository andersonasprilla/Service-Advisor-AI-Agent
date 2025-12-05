import os
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Response 
from twilio.twiml.messaging_response import MessagingResponse

from pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

app = FastAPI()

# --- MEMORY STORAGE ---
user_sessions = {}
# --- AUTHENTICATION ---
allowed_users = ["+15550001234", "+13475108412"]
SHOP_PASSWORD = "HONDA2025"

# --- SETUP ---
# 1. EMBEDDINGS (Keep OpenAI to avoid re-indexing Pinecone)
# Cost: Very cheap (~$0.00002/query). Worth keeping for accuracy.
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# 2. VECTOR DB (Pinecone)
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
pinecone_index = pc.Index("honda-agent")

# --- THE BRAIN (Swapped back to OpenAI for Speed) ---
# Cost: Cheap (~$0.01 for 50 messages)
from langchain_openai import ChatOpenAI

# Use gpt-4o-mini because it is the fastest model they have
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# --- 1. THE ROUTER ---
def identify_vehicle(user_text: str):
    system_prompt = """
    You are a router for a Honda AI. 
    Analyze the user's question and identify if they explicitly mention a car model.
    
    - If they mention a Passport, return: passport-2026
    - If they mention a Civic, return: civic-2025
    - If they mention a Ridgeline, return: ridgeline-2025
    - If they do NOT mention a car, return: unknown
    
    Return ONLY the string.
    """
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"text": user_text}).strip().lower()

# --- 2. THE GUARD ---
def check_for_escalation(user_text: str):
    """
    Checks if the user is angry or asking for a human.
    """
    system_prompt = """
    You are a customer service supervisor. Analyze the user's incoming text.
    
    Return "YES" if:
    1. The user is expressing anger or frustration (swearing, shouting).
    2. The user explicitly asks for a "human", "person", "agent", or "manager".
    
    Return "NO" if:
    1. It is a normal technical question.
    2. They are just saying hello or giving car info.
    
    Return ONLY "YES" or "NO".
    """
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"text": user_text}).strip()

# --- 3. THE SEARCH (RAG) ---
def get_answer_from_manual(question: str, namespace: str):
    print(f"🔎 Searching in drawer: [{namespace}] for: {question}")
    
    query_vector = embeddings.embed_query(question)
    
    search_results = pinecone_index.query(
        vector=query_vector,
        top_k=15, 
        include_metadata=True,
        namespace=namespace
    )
    
    context_text = ""
    for match in search_results['matches']:
        context_text += match['metadata']['text'] + "\n---\n"
        
    prompt_template = ChatPromptTemplate.from_template("""
    You are a helpful Honda Service Advisor Assistant.
    Answer the customer's question ONLY based on the following manual context.
    
    If the answer is NOT in the context, reply exactly with: "NO_ANSWER_FOUND"
    
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

@app.post("/sms")
async def reply_to_sms(Body: str = Form(...), From: str = Form(...)):
    # 1. CLEAN THE NUMBER
    clean_phone = From.replace("whatsapp:", "")
    print(f"📩 Received from {clean_phone}: {Body}")
    
    resp = MessagingResponse()

    # 2. AUTH CHECK
    # We added your number to 'allowed_users' so this should pass now.
    if clean_phone not in allowed_users:
        if Body.strip().upper() == SHOP_PASSWORD:
            allowed_users.append(clean_phone)
            resp.message("✅ Access Granted! Welcome to the Team.")
        else:
            resp.message("🔒 Access Denied. Text the Shop Code (HONDA2025).")
        
        # FIX: Explicitly tell Twilio this is XML
        return Response(content=str(resp), media_type="application/xml")

    # 3. LOGIC (Guard, Router, RAG)
    is_escalation = check_for_escalation(Body)
    if "YES" in is_escalation:
        resp.message("I understand. I have flagged this for Anderson.")
        return Response(content=str(resp), media_type="application/xml")

    detected_car = identify_vehicle(Body)
    target_car = None
    
    if "unknown" not in detected_car:
        target_car = detected_car
        user_sessions[From] = target_car
    elif From in user_sessions:
        target_car = user_sessions[From]

    if target_car:
        ai_answer = get_answer_from_manual(Body, target_car)
        if "NO_ANSWER_FOUND" in ai_answer:
            resp.message("I checked the manual, but I couldn't find that specific detail.")
        else:
            resp.message(ai_answer)
    else:
        resp.message("I can help! Which vehicle is this for? (Passport, Civic, or Ridgeline?)")
    
    # FIX: Explicitly tell Twilio this is XML
    return Response(content=str(resp), media_type="application/xml")