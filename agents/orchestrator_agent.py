"""
OrchestratorAgent — The "front desk" that sits in front of all other agents.

ONE LLM call to classify:
  - intent (tech, booking, escalation, greeting, vehicle_select)
  - vehicle (civic-2025, passport-2026, ridgeline-2025, or null)
  - escalation (true/false)
  - summary (what the customer actually needs)

Replaces the old RouterAgent's 3 separate LLM calls with 1.
Still keeps the phone extraction method (regex-first, LLM fallback).
"""

import re
import json
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from services.clients import get_llm
from config import VEHICLE_NAMESPACES


# The JSON schema we expect back from the LLM
ORCHESTRATOR_PROMPT = """You are the front desk coordinator at Rick Case Honda's AI system.
Analyze the customer's message in ONE pass and return a JSON object.

Available vehicles and their namespaces:
- Honda Civic → "civic-2025"
- Honda Ridgeline → "ridgeline-2025"
- Honda Passport → "passport-2026"

Return ONLY valid JSON (no markdown, no backticks, no explanation):
{{
    "intent": "<one of: tech, booking, escalation, greeting, vehicle_select>",
    "vehicle": "<one of: civic-2025, ridgeline-2025, passport-2026, or null>",
    "escalation": <true if angry/frustrated/asking for human, otherwise false>,
    "summary": "<brief 5-10 word description of what the customer needs>"
}}

INTENT RULES:
- "tech": Customer is asking a question about their vehicle (how-to, specs, warning lights, features, etc.)
- "booking": Customer wants to schedule, book, or make a service appointment. Keywords: book, schedule, appointment, oil change, maintenance, bring my car in, come in.
- "escalation": Customer is angry, frustrated, swearing, or explicitly asking for a human/manager/person.
- "greeting": Customer is just saying hello, thanks, or making small talk.
- "vehicle_select": Customer's message is ONLY a vehicle name (e.g., just "Civic" or "Passport" by itself) — they're selecting which car to talk about.

VEHICLE RULES:
- Set vehicle to the namespace string if they mention a specific Honda model.
- Set vehicle to null if no vehicle is mentioned.
- If the message is ONLY a vehicle name, set intent to "vehicle_select".

ESCALATION RULES:
- Set escalation to true if the customer is angry, using profanity, ALL CAPS shouting, or explicitly asking for a real person.
- If escalation is true, still set intent to "escalation" (overrides other intents).
"""


class OrchestratorAgent:
    """
    Single LLM call to classify every incoming message.
    Returns a structured decision that main.py uses to dispatch.
    """

    def __init__(self):
        self.name = "Orchestrator"

    def classify(self, user_text: str) -> dict:
        """
        Classify a user message into intent + vehicle + escalation.
        
        Returns:
            dict with keys: intent, vehicle, escalation, summary
            Falls back to keyword matching if LLM fails.
        """
        # ── Fast path: try keyword matching first to skip LLM entirely ──
        fast_result = self._fast_classify(user_text)
        if fast_result:
            print(f"   ⚡ {self.name}: Fast-path → {fast_result['intent']} | {fast_result['vehicle']}")
            return fast_result

        # ── Slow path: single LLM call ──
        try:
            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", ORCHESTRATOR_PROMPT),
                ("human", "{text}"),
            ])
            chain = prompt | llm | StrOutputParser()
            raw = chain.invoke({"text": user_text}).strip()

            # Parse JSON response
            # Strip markdown backticks if the LLM wraps them
            cleaned = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(cleaned)

            # Validate and normalize
            result = self._validate(result)
            print(f"   🧠 {self.name}: LLM → {result['intent']} | {result['vehicle']} | escalation={result['escalation']}")
            return result

        except (json.JSONDecodeError, KeyError) as e:
            print(f"   ⚠️ {self.name}: JSON parse error: {e}, raw: {raw[:200]}")
            return self._fallback(user_text)

        except Exception as e:
            print(f"   ❌ {self.name}: Error: {e}")
            return self._fallback(user_text)

    def _fast_classify(self, user_text: str) -> dict | None:
        """
        Keyword-based classification — handles obvious cases without an LLM call.
        Returns None if unsure (triggers LLM path).
        """
        user_lower = user_text.strip().lower()

        # Vehicle select: message is ONLY a vehicle name
        if user_lower in VEHICLE_NAMESPACES:
            return {
                "intent": "vehicle_select",
                "vehicle": VEHICLE_NAMESPACES[user_lower],
                "escalation": False,
                "summary": f"Selected {user_lower}",
            }

        # Booking: clear appointment keywords
        booking_keywords = [
            "book appointment", "schedule service", "make an appointment",
            "schedule appointment", "book service", "need an appointment",
        ]
        if any(kw in user_lower for kw in booking_keywords):
            # Also check for vehicle mention
            vehicle = self._detect_vehicle_keyword(user_lower)
            return {
                "intent": "booking",
                "vehicle": vehicle,
                "escalation": False,
                "summary": "Wants to book appointment",
            }

        # Greeting
        greetings = ["hello", "hi", "hey", "thanks", "thank you", "good morning", "good afternoon"]
        if user_lower in greetings:
            return {
                "intent": "greeting",
                "vehicle": None,
                "escalation": False,
                "summary": "Greeting",
            }

        # If vehicle is mentioned + it's clearly a question → tech
        vehicle = self._detect_vehicle_keyword(user_lower)
        if vehicle and ("?" in user_text or any(w in user_lower for w in ["how", "what", "where", "why", "when", "does", "can", "is the"])):
            return {
                "intent": "tech",
                "vehicle": vehicle,
                "escalation": False,
                "summary": "Technical question",
            }

        # Not obvious enough — let LLM handle it
        return None

    def _detect_vehicle_keyword(self, user_lower: str) -> str | None:
        """Check if a vehicle name appears in the text."""
        for model, namespace in VEHICLE_NAMESPACES.items():
            if model in user_lower:
                return namespace
        return None

    def _validate(self, result: dict) -> dict:
        """Ensure the LLM response has all required fields with valid values."""
        valid_intents = {"tech", "booking", "escalation", "greeting", "vehicle_select"}
        valid_vehicles = set(VEHICLE_NAMESPACES.values()) | {None}

        result.setdefault("intent", "tech")
        result.setdefault("vehicle", None)
        result.setdefault("escalation", False)
        result.setdefault("summary", "")

        if result["intent"] not in valid_intents:
            result["intent"] = "tech"
        if result["vehicle"] not in valid_vehicles:
            result["vehicle"] = None
        if result["escalation"] is True:
            result["intent"] = "escalation"  # Escalation always wins

        return result

    def _fallback(self, user_text: str) -> dict:
        """Last resort if both fast path and LLM fail."""
        print(f"   ⚠️ {self.name}: Using fallback classification")
        user_lower = user_text.lower()

        # Best effort with keywords
        vehicle = self._detect_vehicle_keyword(user_lower)

        booking_keywords = ["book", "schedule", "appointment", "oil change", "maintenance", "bring my car"]
        if any(kw in user_lower for kw in booking_keywords):
            return {"intent": "booking", "vehicle": vehicle, "escalation": False, "summary": "Booking (fallback)"}

        return {"intent": "tech", "vehicle": vehicle, "escalation": False, "summary": "General question (fallback)"}

    # ─── Phone Extraction (kept from RouterAgent — not an LLM classification task) ──

    def extract_phone(self, user_text: str) -> str | None:
        """
        Extract phone number from text.
        Returns formatted string like '(954) 243-1238' or None.
        """
        patterns = [
            r'\(\d{3}\)\s*\d{3}[-\s]?\d{4}',
            r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',
            r'\b\d{10}\b',
        ]
        for pattern in patterns:
            match = re.search(pattern, user_text)
            if match:
                digits = re.sub(r'\D', '', match.group())
                if len(digits) == 10:
                    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

        # LLM fallback
        try:
            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", 'Extract ONLY the phone number. Return in format: (XXX) XXX-XXXX. If none found, return "NO_PHONE".'),
                ("human", "{text}"),
            ])
            chain = prompt | llm | StrOutputParser()
            result = chain.invoke({"text": user_text}).strip()
            return None if "NO_PHONE" in result else result
        except Exception:
            return None


# Singleton
orchestrator = OrchestratorAgent()
