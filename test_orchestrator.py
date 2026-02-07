"""
test_orchestrator.py — Evaluate classification accuracy.
"""
import time
from agents.orchestrator_agent import orchestrator

# Test cases: (Input Text, Expected Intent)
TEST_CASES = [
    ("My check engine light is blinking", "tech"),
    ("I need to schedule an oil change for Tuesday", "booking"),
    ("THIS CAR IS A PIECE OF JUNK I WANT A MANAGER", "escalation"),
    ("Hello there", "greeting"),
    ("Civic", "vehicle_select"),
    ("Make me a sandwich with ham and cheese", "off_topic"), 
    ("Who is the president of the United States?", "off_topic"),
    ("What is the weather in Tokyo?", "off_topic"),
]

def run_tests():
    print("\n🧠 STARTING ORCHESTRATOR EVALUATION")
    print("=" * 60)

    score = 0
    total = len(TEST_CASES)

    for text, expected in TEST_CASES:
        print(f"\n🔹 Input: \"{text}\"")
        
        start = time.time()
        result = orchestrator.classify(text)
        duration = time.time() - start
        
        intent = result["intent"]
        is_correct = (intent == expected)
        
        if is_correct:
            score += 1
            status = "✅ PASS"
        else:
            status = f"❌ FAIL (Got: {intent})"

        print(f"   {status} | Time: {duration:.2f}s")
        if not is_correct:
            print(f"   ⚠️  Expected: {expected}")

    print("\n" + "=" * 60)
    print(f"🏁 FINAL SCORE: {score}/{total} ({(score/total)*100:.0f}%)")

if __name__ == "__main__":
    run_tests()