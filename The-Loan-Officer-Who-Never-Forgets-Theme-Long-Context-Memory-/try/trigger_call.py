import requests
import json

# =========================
# 🔐 EXOTEL CREDENTIALS
# =========================
EXOTEL_SID = "ashutoshshinde1"
API_KEY = "6bb34ec2a75df61f72865e1c4f8927b3390326ed6cc69a06"
API_TOKEN = "a0f0a26c61de5218dd4300edd826a28b4df64e3730d44832"
EXOPHONE_NUMBER = "08047192255" # Replace with your official Exotel number

def start_automated_call(customer_number):
    """
    Triggers an outbound call to the customer.
    When the customer answers, Exotel will hit the 'Url' provided to handle the logic.
    """
    print(f"📞 Starting call to {customer_number}...")
    
    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect.json"
    
    # These parameters connect a customer to a 'Flow' (App)
    # The 'Url' should be your publicly accessible FastAPI endpoint (use ngrok).
    payload = {
        'From': customer_number,
        'CallerId': EXOPHONE_NUMBER,
        'CallType': 'transcribe', # Optional: if you want Exotel's internal transcription
        'StatusCallback': 'https://your-ngrok-url.ngrok-free.app/after_call', # Webhook after call ends
    }
    
    # Note: If you want to connect the customer to a specific App Flow ID:
    # payload['Url'] = f"http://my.exotel.com/{EXOTEL_SID}/exoml/start_voice/{FLOW_ID}"

    try:
        response = requests.post(
            url,
            auth=(API_KEY, API_TOKEN),
            data=payload
        )
        
        if response.status_code == 200:
            print("✅ Call Triggered Successfully!")
            print("Response:", json.dumps(response.json(), indent=4))
        else:
            print(f"❌ Failed to trigger call. Status: {response.status_code}")
            print("Error:", response.text)
            
    except Exception as e:
        print(f"⚠️ Error occurred: {e}")

if __name__ == "__main__":
    # Replace with your own mobile number for testing
    TEST_NUMBER = "8446587383" # <--- YOUR NUMBER HERE
    start_automated_call(TEST_NUMBER)
