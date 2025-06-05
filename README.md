# Lilly, The Hospital Voice Assistant – AI-Powered Call Handler 🏥

**An intelligent voice assistant for hospitals** that interacts with patients in real-time over phone calls, using natural language via Twilio `<Stream>`, OpenAI (STT, Chat, TTS), and FastAPI.

It listens, understands intent, books appointments, and responds instantly — all via a real-time WebSocket pipeline.

---

## 📌 What This Project Does

When a patient calls the hospital:

1. **Twilio** receives the call and sends live audio over a WebSocket.
2. **FastAPI** receives audio frames and transcribes them using **OpenAI STT**.
3. Transcribed text is passed into **OpenAI ChatCompletion** with:
   - Conversation history
   - A function-calling schema
4. **LLM agents** dynamically decide:
   - Whether to *respond conversationally*
   - Or *invoke a backend function* (e.g., `list_doctors`, `book_appointment`)
5. If a function is called:
   - The corresponding function in `crud.py` executes and updates the database.
   - The response is passed back to the LLM for rephrasing into natural language.
6. The final response is spoken using **OpenAI TTS** and played to the caller.
7. All in under ~1 second per interaction.

---


## 🔁 Full Call Flow (LLM + Voice)

```text
Patient → Twilio <Stream> → FastAPI WebSocket /media-stream
         └─ Transcribe (STT) → OpenAI Chat w/ memory + function schema
             └─ LLM decides → [speak OR function call]
                 ├─ If function call → CRUD + DB → response → Chat
                 └─ Final response → TTS → Twilio Playback → Patient
```

---
## LLM Agent Behavior

LLM agent logic is fully dynamic and declarative:

Function schemas are sent as part of the system prompt.
The LLM chooses whether to call a function or not (e.g., list slots, cancel appointment).
After function output, LLM wraps it in natural dialog ("You’re booked with Dr. Kim at 3:00 PM").
No conditional if/else logic needed.

---
## Architecture
![voice_flow_clean](https://github.com/user-attachments/assets/ba63dd0c-0b6c-4060-95ec-86575decef73)



---
## 📡 REST API for Admin Use

1. Method	Endpoint	Description
2. GET	/doctors	List doctors by specialty
3. GET	/slots?doctor_id=1	Available time slots for a doctor
4. POST	/appointments	Book a slot for a patient
5. POST	/tts	Convert text to audio (TTS service)
All routes are documented at /docs (OpenAPI).

---
## 🛠️ Setup

- git clone https://github.com/your-org/hospital-voice-assistant.git
- cd hospital-voice-assistant
- python -m venv env
- source env/bin/activate
- pip install -r requirements.txt
- cp .env.example .env
 edit with your DB + OpenAI + Twilio credentials
- uvicorn app.main:app --reload --port 8010
- 📞 Connect Twilio Voice Stream : Use wss://your-domain/media-stream as the stream URL in Twilio console (enable dual-channel + mute audio).


---
## 🧠 Tech Stack
1. FastAPI – backend API + WebSocket engine
2. Twilio – call streaming and audio playback
3. OpenAI Whisper – speech-to-text
4. OpenAI GPT-4o – dynamic conversation and function calling
5. OpenAI TTS (Alloy voice) – text-to-speech response
6. PostgreSQL + SQLAlchemy – persistent doctor/slot/appointment DB
7. n8n – external automation via REST API

---
## 🧭 Future Roadmap

 1. User Authentication (JWT)
 2. Admin Dashboard (for CRUD and analytics)
 3. Multilingual Support
 4. GPT-function logs for supervision
 5. Retry queue for failed audio responses

 ---
## 💡 Example Use Cases

Patient asks: “Do you have a cardiologist tomorrow afternoon?”


LLM recognizes specialty and date → calls list_doctors and list_slots


Responds with: “Yes! Dr. Samir is available at 2:30 and 3:00 PM. Would you like me to book it?”



---
## Demo


https://github.com/user-attachments/assets/60afc965-bea9-4ad6-abd8-eaee5160b7cb
