"""
test_tech_agent.py — Standalone test runner for the Technical Agent.
"""
import time
from agents.tech_agent import tech_agent  

# 1. Define your test cases (Question + Vehicle Namespace)
TEST_CASES = [
    {
        "vehicle": "civic-2025",
        "query": "How do I reset the low tire pressure warning?",
        "notes": "Should mention the settings menu or TPMS button."
    },
    {
        "vehicle": "ridgeline-2025",
        "query": "What is the towing capacity?",
        "notes": "Should be 5,000 lbs."
    },
    {
        "vehicle": "passport-2026",
        "query": "How do I pair my phone via Bluetooth?",
        "notes": "Look for specific 'Phone' menu steps."
    },
    {
        "vehicle": "civic-2025",
        "query": "Make me a sandwich.",
        "notes": "Should return NO_ANSWER_FOUND or a polite refusal."
    }
]

def run_tests():
    print("\n🧪 STARTING TECH AGENT EVALUATION")
    print("=" * 60)

    for i, test in enumerate(TEST_CASES):
        print(f"\n🔹 Test {i+1}: {test['vehicle'].upper()}")
        print(f"   Query: \"{test['query']}\"")
        
        start = time.time()
        
        # Call the agent directly
        response = tech_agent.run(test['query'], namespace=test['vehicle'])
        
        duration = time.time() - start
        
        print(f"   ⏱️  Time: {duration:.2f}s")
        print(f"   🤖 Response:\n   {'-'*40}")
        print(f"   {response}")
        print(f"   {'-'*40}")
        print(f"   📝 Expected/Notes: {test['notes']}")

if __name__ == "__main__":
    run_tests()