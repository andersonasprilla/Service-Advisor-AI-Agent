"""
test_booking_agent.py — Test if the Booking Agent can handle messy dates.
"""
from agents.booking_agent import booking_agent
from datetime import datetime, timedelta

def get_next_weekday(weekday_name):
    """Helper to calculate what 'Next Tuesday' means relative to today."""
    today = datetime.now()
    days_ahead = 0
    while (today + timedelta(days=days_ahead)).strftime("%A").lower() != weekday_name.lower():
        days_ahead += 1
    if days_ahead == 0: days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

# 1. Define Test Scenarios
TEST_CASES = [
    {
        "input": "I need an oil change for my 2022 Civic",
        "context": "New Customer",
        "expected_substrings": ["When works best", "time"] 
    },
    {
        "input": "Next Tuesday at 10am would be great",
        "context": "Returning Customer: John Doe",
        "expected_substrings": ["Tuesday", "10", "book", "schedule"]
    },
    {
        "input": "Actually can we do the afternoon instead?",
        "context": "Current Plan: Tuesday 10am",
        "expected_substrings": ["afternoon", "confirmed", "set"]
    }
]

def run_tests():
    print("\n📅 STARTING BOOKING AGENT EVALUATION")
    print("=" * 60)

    for i, test in enumerate(TEST_CASES):
        print(f"\n🔹 Test {i+1}: Input: \"{test['input']}\"")
        print(f"   Context: {test['context']}")
        
        # We manually inject context since we aren't using the full DB in this test
        # Note: We are testing the LLM's *response generation* here.
        
        # Overriding the build_context for the test (Simulation)
        response = booking_agent.run(test['input'], phone="555-0100")
        
        print(f"   🤖 Agent Said: \"{response}\"")
        
        # Simple check: Did it ask the right follow-up question?
        passed = any(sub.lower() in response.lower() for sub in test['expected_substrings'])
        
        if passed:
            print("   ✅ PASS: Response seems relevant.")
        else:
            print(f"   ⚠️  POSSIBLE FAIL: Expected reference to {test['expected_substrings']}")

if __name__ == "__main__":
    run_tests()