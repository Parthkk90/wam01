import requests
import sqlite3

OLLAMA_URL = "http://localhost:11434/api/generate"

SYSTEM_PROMPT = """
Tum ek professional loan officer ho — BrainBack Bank ke liye.
Tumhara naam hai "Aryan".

Rules:
- Hinglish mein baat karo (Hindi + English mix)
- Friendly aur professional raho
- Loan related questions poocho — salary, EMI, co-applicant
- Ek baar mein sirf ek question poocho
- Short rakho — 2-3 sentences max
- PAN/Aadhaar mat maango — sirf verbal info lo

Shuru karo greeting se agar pehla message hai.
"""

def get_conversation_history(call_sid: str) -> str:
    """Pichli baatein DB se load karo"""
    conn = sqlite3.connect("conversations.db")
    rows = conn.execute(
        """SELECT speaker, text FROM conversations
           WHERE call_sid=? ORDER BY timestamp""",
        (call_sid,)
    ).fetchall()
    conn.close()

    history = ""
    for speaker, text in rows:
        prefix = "Customer" if speaker == "Customer" else "Agent (Aryan)"
        history += f"{prefix}: {text}\n"
    return history

def get_ai_reply(call_sid: str, customer_text: str) -> str:
    history = get_conversation_history(call_sid)

    prompt = f"""
{SYSTEM_PROMPT}

Conversation so far:
{history}

Customer ne abhi kaha: "{customer_text}"

Aryan ka reply (sirf reply likho, kuch aur nahi):
"""

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "phi4-mini",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 100   # short reply
            }
        })
        return response.json()["response"].strip()

    except Exception as e:
        print(f"Ollama error: {e}")
        return "Sorry, ek second — kya aap dobara bol sakte hain?"