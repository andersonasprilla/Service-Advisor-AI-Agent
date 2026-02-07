"""
BookingAgent — Handles appointment-related conversation with customer context.

Context comes from the customer database (CSV records).
"""

from agents.base_agent import BaseAgent
from services.customer_database import customer_db


class BookingAgent(BaseAgent):

    system_prompt_template = """You are the Booking Scheduler for Rick Case Honda.
Your goal is to help customers book service appointments.

### CUSTOMER CONTEXT
{context}

### RULES
1. If Date/Time is missing, ask for it.
2. Keep responses short (SMS style).
3. Be friendly and professional."""

    def __init__(self):
        super().__init__(name="BookingAgent")

    def build_context(self, user_message: str, **kwargs) -> str:
        """Look up customer info from the database."""
        phone = kwargs.get("phone")
        if not phone:
            return "New Customer (no phone provided)"

        print(f"   📅 {self.name}: Looking up phone {phone}...")
        customer = customer_db.search_by_phone(phone)

        if customer:
            return (
                f"Returning Customer: {customer['name']}\n"
                f"Vehicle: {customer['last_vehicle']}\n"
                f"Visit Count: {customer['visit_count']}\n"
                f"Last Service: {customer['last_service']}"
            )
        return "New Customer"


# Convenience singleton
booking_agent = BookingAgent()
