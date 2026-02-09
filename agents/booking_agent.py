"""
BookingAgent — Conversational appointment scheduling.

Instead of a rigid state machine (phone → name → vehicle → service → date → time),
this agent has a natural conversation. The LLM extracts info as it comes and only
asks for what's missing — all in the customer's language.

The LLM returns:
  1. A natural reply to the customer
  2. A JSON block with extracted fields

When all required fields are collected, the appointment is finalized.
"""

import json
import re
from datetime import datetime
from services.clients import get_llm


BOOKING_SYSTEM_PROMPT = """You're a service advisor at Rick Case Honda, texting with a customer to schedule a service appointment.

TODAY: __CURRENT_TIME__
LANGUAGE: Respond in __LANGUAGE__. Be natural — text like a native speaker of that language.
CUSTOMER INFO: __CUSTOMER_CONTEXT__

YOUR JOB:
You're having a natural text conversation to book an appointment. Extract info as the customer gives it — don't interrogate them one question at a time. If they say "necesito un cambio de aceite para mi Civic mañana en la mañana", you already have the service, vehicle, date AND time in one message.

REQUIRED FIELDS (to complete a booking):
- name: Customer's name
- phone: Phone number (format: (XXX) XXX-XXXX)
- vehicle: What car they're bringing in
- service_type: What they need done
- preferred_date: When (convert relative dates like "tomorrow" to actual dates based on TODAY)
- preferred_time: What time (morning/afternoon/specific time all work)

STYLE:
- Text like a real person. Short, warm, casual.
- NO numbered lists, NO bullet points, NO bold. Just natural texting.
- If you already have some info from the customer context, use it — don't ask again.
- Ask for missing info naturally, combining questions when it flows. Example: "What are we doing and when works for you?" instead of asking separately.
- When confirming, keep it brief and friendly.

RESPONSE FORMAT:
Write your natural reply to the customer, then on a new line add a JSON block with what you've extracted so far.
The customer will NOT see the JSON — only your reply.

YOUR_REPLY_HERE
[BOOKING_DATA]
{"name": "...", "phone": "...", "vehicle": "...", "service_type": "...", "preferred_date": "...", "preferred_time": "...", "complete": true/false}
[/BOOKING_DATA]

RULES FOR THE JSON:
- Use null for fields you don't have yet.
- Set "complete": true ONLY when ALL 6 fields are filled.
- When complete is true, your reply should be a natural confirmation message.
- For returning customers, pre-fill what you know from CUSTOMER INFO.
- Convert relative dates: "tomorrow" → actual date, "next Tuesday" → actual date.
"""


class BookingAgent:
    """
    Conversational booking — no state machine, just a natural chat.
    
    The appointment_data dict stores:
      - "messages": conversation history for the LLM
      - "extracted": running dict of extracted fields
      - all extracted fields at top level for saving
    """

    def __init__(self):
        self.name = "BookingAgent"

    def run(self, user_message: str, appointment: dict, session: dict) -> tuple[str, bool]:
        """
        Process a booking message.
        
        Args:
            user_message: What the customer said
            appointment: The appointment_data[user_id] dict (mutable)
            session: The user_sessions[user_id] dict (for language, vehicle info)
        
        Returns:
            (reply_text, is_complete) — reply to send, and whether booking is done
        """
        language = session.get("language", "en")
        lang_names = {
            "en": "English", "es": "Spanish", "pt": "Portuguese",
            "fr": "French", "ht": "Haitian Creole", "zh": "Chinese",
        }
        lang_label = lang_names.get(language, language)
        now_str = datetime.now().strftime("%A, %b %d, %Y at %I:%M %p")

        # Build customer context from session
        customer_context = self._build_customer_context(appointment, session)

        # Build conversation history
        if "messages" not in appointment:
            appointment["messages"] = []

        appointment["messages"].append(f"Customer: {user_message}")

        # Format the full conversation for the LLM
        conversation = "\n".join(appointment["messages"])

        system_content = BOOKING_SYSTEM_PROMPT \
            .replace("__CURRENT_TIME__", now_str) \
            .replace("__LANGUAGE__", lang_label) \
            .replace("__CUSTOMER_CONTEXT__", customer_context)

        try:
            llm = get_llm()
            
            # Build messages directly — bypass ChatPromptTemplate to avoid
            # curly brace parsing on the JSON example in the system prompt
            from langchain_core.messages import SystemMessage, HumanMessage
            
            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=f"Conversation so far:\n{conversation}\n\nRespond to the customer's latest message."),
            ]
            
            result = llm.invoke(messages)
            raw_response = result.content

            # Parse the response and JSON
            reply, extracted = self._parse_response(raw_response)

            # Update appointment data with extracted fields
            if extracted:
                for key in ["name", "phone", "vehicle", "service_type", "preferred_date", "preferred_time"]:
                    if extracted.get(key) and extracted[key] != "null":
                        appointment[key] = extracted[key]

                is_complete = extracted.get("complete", False)
            else:
                is_complete = False

            # Add bot reply to conversation history
            appointment["messages"].append(f"Advisor: {reply}")

            # Keep conversation history manageable
            if len(appointment["messages"]) > 20:
                appointment["messages"] = appointment["messages"][-12:]

            print(f"   📅 {self.name}: extracted={json.dumps({k: appointment.get(k) for k in ['name','phone','vehicle','service_type','preferred_date','preferred_time']}, default=str)}")
            print(f"   📅 {self.name}: complete={is_complete}")

            return reply, is_complete

        except Exception as e:
            print(f"   ❌ {self.name} Error: {e}")
            error_msgs = {
                "es": "Algo falló por acá. ¿Puedes intentar de nuevo?",
                "pt": "Algo deu errado aqui. Pode tentar de novo?",
            }
            return error_msgs.get(language, "Something went wrong on my end. Can you try that again?"), False

    def _build_customer_context(self, appointment: dict, session: dict) -> str:
        """Build context string from what we know about the customer."""
        parts = []

        if session.get("customer_name"):
            parts.append(f"Name: {session['customer_name']}")
        elif appointment.get("name"):
            parts.append(f"Name: {appointment['name']}")

        if session.get("phone"):
            parts.append(f"Phone: {session['phone']}")
        elif appointment.get("phone"):
            parts.append(f"Phone: {appointment['phone']}")

        if session.get("vehicle_label"):
            parts.append(f"Vehicle: {session['vehicle_label']}")
        elif appointment.get("vehicle"):
            parts.append(f"Vehicle: {appointment['vehicle']}")

        if session.get("vin"):
            parts.append(f"VIN: {session['vin']}")

        if appointment.get("service_type"):
            parts.append(f"Service needed: {appointment['service_type']}")

        return "\n".join(parts) if parts else "New customer — no info on file yet."

    def _parse_response(self, raw: str) -> tuple[str, dict | None]:
        """
        Split the LLM response into:
          - Customer-facing reply
          - Extracted JSON data
        """
        # Try to extract JSON from [BOOKING_DATA] tags
        json_match = re.search(r'\[BOOKING_DATA\]\s*(\{.*?\})\s*\[/BOOKING_DATA\]', raw, re.DOTALL)

        if json_match:
            reply = raw[:json_match.start()].strip()
            try:
                extracted = json.loads(json_match.group(1))
                return reply, extracted
            except json.JSONDecodeError:
                print(f"   ⚠️ {self.name}: JSON parse failed")
                return reply, None

        # Fallback: try to find any JSON object in the response
        json_fallback = re.search(r'\{[^{}]*"complete"[^{}]*\}', raw, re.DOTALL)
        if json_fallback:
            reply = raw[:json_fallback.start()].strip()
            try:
                extracted = json.loads(json_fallback.group())
                return reply, extracted
            except json.JSONDecodeError:
                pass

        # No JSON found — just return the whole thing as reply
        return raw.strip(), None


# Singleton
booking_agent = BookingAgent()
