def __getattr__(name):
    if name == "tech_agent":
        from agents.tech_agent import tech_agent
        return tech_agent
    elif name == "booking_agent":
        from agents.booking_agent import booking_agent
        return booking_agent
    elif name == "orchestrator":
        from agents.orchestrator_agent import orchestrator
        return orchestrator
    elif name == "BaseAgent":
        from agents.base_agent import BaseAgent
        return BaseAgent
    raise AttributeError(f"module 'agents' has no attribute {name}")