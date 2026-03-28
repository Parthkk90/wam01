# 🏦 The Loan Officer Who Never Forgets
### *BrainBack.AI — A Theme-Based Long-Context Memory System*

---

## 🏗️ Project Overview

**BrainBack.AI** is a state-of-the-art voice terminal designed for loan officers. It integrates real-time AI voice interaction with a persistent memory system, ensuring that every conversation detail is captured and used to build stronger client relationships.

> **"A loan officer who remembers everything is an officer who wins."**

---

## ✨ Key Features

- 🎧 **Real-time Voice Interface**: High-fidelity, low-latency calls directly from the browser.
- 🗣️ **Hinglish AI Persona**: The assistant ("Aryan") speaks in natural Hindi + English mix for a familiar local experience.
- 📃 **Live Transcription**: Every word spoken is transcribed in real-time onto your dashboard and terminal.
- 🧠 **Memory Engine**: Optimized for long-context memory to recall salary, EMI, and co-applicant details.
- 🎨 **Premium UI**: Sleek, glassmorphic terminal design for a modern professional workflow.

---

## 🚀 Quick Start Guide

### 1️⃣ Prerequisites
- **Python 3.8+**
- A **Vapi.ai** account for API keys.

### 2️⃣ Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/ashutosh2975/The-Loan-Officer-Who-Never-Forgets-Theme-Long-Context-Memory-.git
    cd ARISE
    ```

2.  **Environment Setup:**
    ```bash
    python -m venv venv
    .\venv\Scripts\activate   # For Windows
    # source venv/bin/activate # For Mac/Linux
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

---

### 3️⃣ Configuration (`.env`)

Create a `.env` file in the root directory and paste your Vapi credentials:

```env
# Vapi Credentials (from https://dashboard.vapi.ai)
VAPI_API_KEY=your_vapi_api_key
VAPI_PUBLIC_KEY=your_vapi_public_key
VAPI_ASSISTANT_ID=your_vapi_assistant_id

# Server Config
PORT=8000
```

---

### 4️⃣ Launch the System

Start the production-ready FastAPI backend:

```bash
uvicorn app.main:app --reload --port 8000
```

🚀 **Terminal Link**: [http://localhost:8000](http://localhost:8000)

---

## 📁 File Structure

| Path | Description |
| :--- | :--- |
| `app/main.py` | Core FastAPI application entry point |
| `app/static/` | Glassmorphic Frontend (HTML/CSS) |
| `app/routes/` | API Business logic & Webhook handlers |
| `try/` | Experimental AI R&D (Faster-Whisper & Ollama) |
| `TECHNICAL_GUIDE.md` | Deep dive for developers |

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python)
- **Voice SDK**: Vapi AI
- **Frontend**: Vanilla JS / CSS3 (Terminal-UI)
- **Transcription**: Faster-Whisper (Experimental local support)
- **AI Models**: GPT-4o / Phi-4 (via Ollama)

---
*Built with ❤️ for the future of resilient banking.*  
#   T h e - L o a n - O f f i c e r - W h o - N e v e r - F o r g e t s - T h e m e - L o n g - C o n t e x t - M e m o r y -