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
        "session": {
            "language": "en",
            "phone": None,
            "customer_name": None,
            "vehicle_label": None,
        },
        "appointment": {
            "messages": [],
        },
        "expected_substrings": ["phone", "number", "contact"] 
    },
    {
        "input": "Next Tuesday at 10am would be great",
        "session": {
            "language": "en",
            "phone": "(954) 555-0100",
            "customer_name": "John Doe",
            "vehicle_label": "2022 Honda Civic",
        },
        "appointment": {
            "messages": ["Customer: I need an oil change", "Advisor: What's your phone number?", "Customer: 954-555-0100"],
            "phone": "(954) 555-0100",
            "name": "John Doe",
            "vehicle": "2022 Honda Civic",
            "service_type": "oil change",
        },
        "expected_substrings": ["Tuesday", "10", "confirm", "set"]
    },
    {
        "input": "Actually can we do the afternoon instead?",
        "session": {
            "language": "en",
            "phone": "(954) 555-0100",
            "customer_name": "John Doe",
            "vehicle_label": "2022 Honda Civic",
        },
        "appointment": {
            "messages": [
                "Customer: I need an oil change",
                "Advisor: What's your phone number?",
                "Customer: 954-555-0100",
                "Advisor: When works for you?",
                "Customer: Next Tuesday at 10am"
            ],
            "phone": "(954) 555-0100",
            "name": "John Doe",
            "vehicle": "2022 Honda Civic",
            "service_type": "oil change",
            "preferred_date": get_next_weekday("Tuesday"),
            "preferred_time": "10am",
        },
        "expected_substrings": ["afternoon", "confirm", "set"]
    },
    {
        "input": "Necesito un cambio de aceite para mañana en la mañana",
        "session": {
            "language": "es",
            "phone": None,
            "customer_name": None,
            "vehicle_label": None,
        },
        "appointment": {
            "messages": [],
        },
        "expected_substrings": ["teléfono", "número", "contacto"]
    }
]

def run_tests():
    print("\n📅 STARTING BOOKING AGENT EVALUATION")
    print("=" * 60)

    for i, test in enumerate(TEST_CASES):
        print(f"\n🔹 Test {i+1}: Input: \"{test['input']}\"")
        print(f"   Language: {test['session']['language']}")
        
        # Call with correct signature: (user_message, appointment, session)
        response, is_complete = booking_agent.run(
            test['input'],
            test['appointment'],
            test['session']
        )
        
        print(f"   🤖 Agent Said: \"{response}\"")
        print(f"   📊 Complete: {is_complete}")
        
        # Simple check: Did it ask the right follow-up question?
        passed = any(sub.lower() in response.lower() for sub in test['expected_substrings'])
        
        if passed:
            print("   ✅ PASS: Response seems relevant.")
        else:
            print(f"   ⚠️  POSSIBLE FAIL: Expected reference to {test['expected_substrings']}")
        
        # Show extracted data
        if test['appointment']:
            extracted = {k: v for k, v in test['appointment'].items() 
                        if k not in ['messages'] and k in ['name', 'phone', 'vehicle', 'service_type', 'preferred_date', 'preferred_time']}
            if extracted:
                print(f"   📋 Extracted: {extracted}")

if __name__ == "__main__":
    run_tests()
