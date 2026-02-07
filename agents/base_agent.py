"""
BaseAgent — The common pattern all agents share.

Every agent:
  1. Builds context  (override `build_context`)
  2. Has a system prompt template
  3. Calls the LLM
  4. Returns the response

Subclasses only need to define their prompt and how they gather context.
"""

from abc import ABC, abstractmethod
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from services.clients import get_llm


class BaseAgent(ABC):
    """Abstract base for all Rick Case Honda agents."""

    # Subclasses set this — a string with {context} placeholder
    system_prompt_template: str = ""

    def __init__(self, name: str = "BaseAgent"):
        self.name = name

    @abstractmethod
    def build_context(self, user_message: str, **kwargs) -> str:
        """
        Gather whatever context this agent needs.
        
        Returns a string that gets injected into the system prompt.
        """
        ...

    def run(self, user_message: str, **kwargs) -> str:
        """
        Main entry point — shared by ALL agents.
        
        1. Build context (agent-specific)
        2. Format system prompt
        3. Call LLM
        4. Return response string
        """
        print(f"   🤖 {self.name}: Processing...")

        try:
            # 1. Build context
            context = self.build_context(user_message, **kwargs)

            # 2. Format system prompt
            system_content = self.system_prompt_template.format(context=context)

            # 3. Call LLM
            llm = get_llm()
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_content),
                ("human", "{input}"),
            ])
            chain = prompt | llm | StrOutputParser()
            response = chain.invoke({"input": user_message})

            print(f"   ✅ {self.name}: Done")
            return response

        except Exception as e:
            print(f"   ❌ {self.name} Error: {e}")
            return (
                f"I encountered an error while processing your request. "
                f"Please try again or contact service directly."
            )
