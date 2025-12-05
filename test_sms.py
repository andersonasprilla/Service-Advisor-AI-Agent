import requests

# This URL matches where your FastAPI server is running locally
url = "http://127.0.0.1:8000/sms"

# This simulates the data Twilio would send
payload = {
    "Body": "How much oil does the Ridgeline take?",
    "From": "+15550001234"
}

print(f"Sending message: '{payload['Body']}' to {url}...")

try:
    response = requests.post(url, data=payload)
    
    if response.status_code == 200:
        print("\n✅ SUCCESS! The server replied:")
        print(response.text)
    else:
        print(f"\n❌ ERROR: Server returned {response.status_code}")
        print("Did you save the main.py file? Is the @app.post('/sms') route defined?")
        
except Exception as e:
    print(f"\n❌ CONNECTION FAILED: {e}")
    print("Is the server running? (Did you run 'uvicorn main:app --reload'?)")