# 🛠️ Technical Implementation Guide: BrainBack.AI

This document provides a deep dive into the technical architecture of the **BrainBack.AI Loan Officer Memory System**. If you're a developer looking to understand how we integrated real-time voice with a FastAPI backend, this guide is for you.

---

## 🏗️ System Architecture

The project is built using a **Decoupled Client-Server-Cloud** architecture.

### 1. Frontend: The Voice Terminal
- **Stack**: Vanilla HTML5, CSS3 (Glassmorphism), JavaScript (ESM).
- **Voice Integration**: We use the `@vapi-ai/web` SDK.
- **Workflow**:
    - The browser initiates a secure handshake with Vapi Cloud using a `publicKey`.
    - Once the call is started using an `assistantId`, Vapi handles the **WebRTC** connection for low-latency audio.
    - **Event Handling**: We listen for `call-start`, `call-end`, and `message`. The `message` event provides **real-time transcripts** (both user and AI) which are dynamically injected into the DOM.

### 2. Backend: FastAPI Service
- **Stack**: Python, FastAPI, Uvicorn.
- **Role**: The backend serves two main purposes:
    - **Config Injection**: Serves the `VAPI_PUBLIC_KEY` and `ASSISTANT_ID` from environment variables to the frontend to ensure security.
    - **Webhook Processing**: Vapi sends POST requests to `/api/vapi/webhook` at different stages (start, transcript, end). We process these to log conversations server-side.
- **Mocking Strategy**: Since we are in the MVP stage, the database is currently mocked (`app/database.py`), logging transcripts directly to the terminal for debugging.

### 3. Speech-to-Text (ASR) Strategies
We have two levels of ASR implementation:
- **Cloud-Native (Vapi)**: Used in the live UI for sub-second latency. It handles the full stack (STT -> LLM -> TTS).
- **Local/Experimental (Faster-Whisper)**: Found in `try/transcribe.py`. We use the `large-v3-turbo` model with **INT8 quantization** to run efficiently on a CPU. This is intended for offline processing or high-accuracy archival transcription.

---

## 🧠 AI Intelligence Layer

The "Loan Officer" persona (Aryan) is steered via two methods in the codebase:
1.  **Vapi System Prompt**: Set in the Vapi Dashboard for the live assistant.
2.  **Ollama Experiment (`try/ai_agent.py`)**: For local R&D, we use the `phi4-mini` model via Ollama. It follows a system prompt that enforces:
    - **Hinglish** (Hindi + English) code-switching.
    - **Professional Loan Persona**.
    - **One-question-at-a-time** constraint to maintain user engagement.

---

## 🔄 The Data Flow

1.  **User Clicks Call**: Browser loads JS SDK -> Fetches config from `/api/config` -> Handshake with Vapi.
2.  **Voice Activity**: User speaks -> Vapi Streams Audio -> ASR converts to Text -> LLM generates Response -> TTS streams Audio back to User.
3.  **Webhook Sync**: Vapi hits the FastAPI `/api/vapi/webhook` with the transcript -> Backend prints the dialog to the terminal console with emojis (🧑 USER | 🤖 ASSISTANT).
4.  **Session End**: Vapi sends an `end-of-call-report`, which the backend processes to show the full conversation summary and duration.

---

## 🔧 Developer Notes: How to Extend

- **Database Persistence**: To log sessions permanently, replace the logic in `app/routes/calls.py` to write to a PostgreSQL/SQLite database within the `handle_call_end` function.
- **Custom STT**: If you want to use local models like **IndicASR**, you'd need to pipe the Vapi audio stream to your own server, though Vapi's built-in ASR is currently optimized for this speed.
- **LLM Swap**: The `VAPI_ASSISTANT_ID` points to a hosted model (like GPT-4o or Groq Llama 3). You can swap this to any provider via the Vapi Dashboard without changing a single line of frontend code.

---
*Developed for the "Loan Officer Who Never Forgets" theme.*
