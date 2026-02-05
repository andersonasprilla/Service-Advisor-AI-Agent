# router.py
from openai import OpenAI
import os

# Initialize Client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ROUTER_PROMPT = """
You are the Router for Rick Case Honda.
Classify the user's message into exactly one of these categories:

1. BOOKING: User wants to schedule, check, cancel, or reschedule service.
2. TECHNICAL: User asks about maintenance codes (A17, B1), lights, noise, or vehicle parts.
3. GENERAL: Greetings, "thank you", or off-topic chitchat.

MESSAGE: "{message}"

Return ONLY one word: BOOKING, TECHNICAL, or GENERAL.
"""

def classify_intent(user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Or gpt-3.5-turbo for speed
            messages=[
                {"role": "system", "content": ROUTER_PROMPT.format(message=user_message)}
            ],
            temperature=0
        )
        
        intent = response.choices[0].message.content.strip().upper()
        
        if intent in ["BOOKING", "TECHNICAL", "GENERAL"]:
            return intent
        return "GENERAL"
    except Exception as e:
        print(f"⚠️ Router Error: {e}")
        return "GENERAL"