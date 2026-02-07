"""
BookingAgent — Handles appointment conversations with time awareness.
"""

from datetime import datetime
from agents.base_agent import BaseAgent
from services.customer_database import customer_db

class BookingAgent(BaseAgent):

    # 1. Update the System Prompt to include a {current_time} placeholder
    system_prompt_template = """You are the Booking Scheduler for Rick Case Honda.
Your goal is to help customers book service appointments.

### CURRENT TIME
Today is: {current_time}
(Use this to calculate relative dates like "next Tuesday")

### CUSTOMER CONTEXT
{context}

### RULES
1. If the user gives a relative time (like "tomorrow"), confirm the actual date (e.g., "Great, that's Wednesday, Oct 25th").
2. If Date/Time is missing, ask for it.
3. Keep responses short (SMS style).
4. Be friendly and professional.
"""

    def __init__(self):
        super().__init__(name="BookingAgent")

    def build_context(self, user_message: str, **kwargs) -> str:
        """
        Build context including:
        1. Customer DB info
        2. The Current Date/Time
        """
        phone = kwargs.get("phone")
        
        # Get Customer Info
        if phone:
            print(f"   📅 {self.name}: Looking up phone {phone}...")
            customer = customer_db.search_by_phone(phone)
            if customer:
                customer_info = (
                    f"Returning Customer: {customer['name']}\n"
                    f"Vehicle: {customer['last_vehicle']}\n"
                    f"Last Service: {customer['last_service']}"
                )
            else:
                customer_info = "New Customer"
        else:
            customer_info = "New Customer (No phone)"

        return customer_info

    # Override run to inject current_time into the prompt formatting
    def run(self, user_message: str, **kwargs) -> str:
        """
        We override run() to inject {current_time} into the prompt.
        """
        # Get the standard context (Customer Info)
        context_str = self.build_context(user_message, **kwargs)
        
        # Get the current date formatted nicely (e.g., "Friday, Feb 07, 2026")
        now_str = datetime.now().strftime("%A, %b %d, %Y")

        # Format the system prompt with BOTH pieces of info
        system_content = self.system_prompt_template.format(
            context=context_str,
            current_time=now_str
        )
        
        # --- The rest is standard BaseAgent logic ---
        from services.clients import get_llm
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        print(f"   🤖 {self.name}: Processing with date {now_str}...")

        try:
            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_content),
                ("human", "{input}"),
            ])
            chain = prompt | llm | StrOutputParser()
            response = chain.invoke({"input": user_message})
            return response

        except Exception as e:
            print(f"   ❌ {self.name} Error: {e}")
            return "I'm having trouble checking the calendar. Can you try again?"

# Singleton
booking_agent = BookingAgent()