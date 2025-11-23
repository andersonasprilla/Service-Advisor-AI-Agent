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

# --- MEMORY STORAGE ---
user_sessions = {}

# --- 1. THE ROUTER (Identifies Car) ---
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

# --- 2. THE GUARD (New: Checks for Anger/Human Request) ---
def check_for_escalation(user_text: str):
    """
    Checks if the user is angry or asking for a human.
    Returns 'YES' if we need to hand off, 'NO' if we can handle it.
    """
    system_prompt = """
    You are a customer service supervisor. Analyze the user's incoming text.
    
    Return "YES" if:
    1. The user is expressing anger or frustration (swearing, shouting).
    2. The user explicitly asks for a "human", "person", "agent", or "manager".
    
    Return "NO" if:
    1. It is a normal technical question (even if short).
    2. They are just saying hello or giving car info.
    
    Return ONLY "YES" or "NO".
    """
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{text}")])
    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"text": user_text}).strip()
    return result

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
        
    # We update the prompt to allow the AI to admit defeat cleanly
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

@app.get("/")
async def health_check():
    return {"message": "Honda Agent with Escalation is awake!"}

@app.post("/sms")
async def reply_to_sms(Body: str = Form(...), From: str = Form(...)):
    print(f"📩 Received from {From}: {Body}")
    resp = MessagingResponse()

    # --- STEP A: Check if user is angry or wants a human ---
    is_escalation = check_for_escalation(Body)
    if is_escalation == "YES":
        print("🚨 SENTIMENT ALERT: User is angry or asking for human.")
        resp.message("I understand you'd like to speak with someone. I have flagged this conversation for Anderson (Senior Advisor). He will text you personally in a moment.")
        # In a real app, you would send an email/text to YOURSELF here.
        return str(resp)

    # --- STEP B: Vehicle Logic ---
    detected_car = identify_vehicle(Body)
    target_car = None
    
    if detected_car != "unknown":
        target_car = detected_car
        user_sessions[From] = target_car
    elif From in user_sessions:
        target_car = user_sessions[From]

    if target_car:
        # --- STEP C: Get Answer ---
        ai_answer = get_answer_from_manual(Body, target_car)
        
        # --- STEP D: Check for AI Failure ---
        if "NO_ANSWER_FOUND" in ai_answer:
            print("❌ RAG FAILURE: Manual didn't have the answer.")
            resp.message("I checked the 2025 manual, but I couldn't find that specific detail. I've notified a human Service Advisor to check the shop system for you.")
        else:
            resp.message(ai_answer)
    else:
        resp.message("I can help with that! Which vehicle is this for? (Passport, Civic, or Ridgeline?)")
    
    return str(resp)