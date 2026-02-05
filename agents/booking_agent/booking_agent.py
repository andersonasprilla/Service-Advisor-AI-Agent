# agents/booking_agent.py
from openai import OpenAI
from customer_database import customer_db
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BOOKING_PROMPT = """
You are the Booking Scheduler for Rick Case Honda.
Your goal is to book appointments.

### CUSTOMER CONTEXT
{customer_context}

### RULES
1. If Date/Time is missing, ask for it.
2. Keep responses short (SMS style).
"""

def run_booking_agent(user_message, phone):
    print("   📅 Booking Agent: Checking Database...")
    
    # 1. Database Lookup
    customer = customer_db.search_by_phone(phone)
    if customer:
        context = f"Returning Customer: {customer['name']}, Vehicle: {customer['last_vehicle']}"
    else:
        context = "New Customer"

    # 2. Generate Response
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": BOOKING_PROMPT.format(customer_context=context)},
            {"role": "user", "content": user_message}
        ]
    )
    
    return response.choices[0].message.content