# EMMA Voice Bot

A voice reception agent for a fictional GP surgery. You talk to it over a live call in the browser; it answers practice questions from a knowledge base, books appointments against a database, and handles medical emergencies with a fixed response that the language model never gets to override.

Speech-to-text, the LLM and text-to-speech all run locally. The only external service is Twilio, which carries the call audio and does no processing.

## The idea worth reading first

Two decisions are made in plain Python **before the LLM is ever called**, not left to a prompt:

1. **Emergency gate.** Every transcribed turn is checked against a set of red-flag patterns (chest pain, can't breathe, unresponsive, stroke signs, self-harm, overdose, and so on). A match plays a fixed "call 999" message and skips the model entirely for that turn.
2. **Grounding gate.** Factual questions are searched against the knowledge base first. If nothing scores above the similarity threshold, the bot returns a fixed "please call the surgery" reply without calling the LLM, so it cannot invent an answer it has no source for.

A prompt saying "don't hallucinate" is a suggestion the model can still get wrong. A code path that never reaches the model cannot.

## How a turn works

```
browser (Twilio Voice JS SDK, WebRTC)
   -> Twilio -> Media Stream WebSocket -> Flask /media-stream
        1. buffer audio until ~1.2 s of silence
        2. speech-to-text        faster-whisper (base.en, CPU, int8)
        3. emergency gate        safety.py  -> fixed message, no LLM
        4. booking intent?       keyword match, stays on for the rest of the call
              yes -> LLM with a book_appointment tool, live MySQL availability injected each turn
              no  -> RAG: FAISS over knowledge_base/ -> grounded LLM answer, or fixed refusal
        5. text-to-speech        Coqui TTS (Tacotron2-DDC), resampled to 8 kHz mu-law
   <- audio streamed back over the same WebSocket
```

The call page also shows a live transcript panel. It is fed by Server-Sent Events from the same log lines the server prints, so what you see on screen matches the console exactly.

## Stack

| Layer | Choice |
|---|---|
| Call transport | Twilio Voice JS SDK + Media Streams (browser calling, no phone number) |
| Backend | Flask, flask-sock |
| Speech-to-text | faster-whisper, `base.en`, CPU int8 |
| LLM | Ollama, `llama3.2:3b` |
| Text-to-speech | Coqui TTS, `tacotron2-DDC` |
| Retrieval | sentence-transformers `all-MiniLM-L6-v2` + FAISS |
| Database | MySQL 8.4 (synthetic data only) |

## Setup

Requires Python 3.11 (the audio path uses `audioop`, which was removed in Python 3.13), MySQL, Ollama and a Twilio account.

1. **Python deps**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Model:** install [Ollama](https://ollama.com), then `ollama pull llama3.2:3b`. Whisper and Coqui weights download automatically on first run.
3. **Database:** create a database called `emma_demo` and apply `schema.sql`. Booking slots are seeded automatically at startup.
   On Windows, keep the MySQL data directory at a plain path such as `C:\mysql-data`; a nested or dot-prefixed directory triggered an InnoDB startup error in my setup.
4. **Twilio:** create an API key and a TwiML Application whose Voice request URL is `https://<your-ngrok-domain>/webhook/voice`.
5. **Config:** copy `.env.example` to `.env` and fill in the Twilio Account SID, API key, API secret and TwiML App SID.

## Run

```bash
python app.py                # loads all models, then serves on :5000
ngrok http 5000              # public HTTPS/WSS URL for Twilio
```

Open `http://localhost:5000/static/call.html`, wait for **ready**, and click **Call EMMA**.

Things to try:

- "What are your opening hours?" - grounded answer
- "I'd like to book an appointment" - multi-turn booking against MySQL
- "I have chest pain and can't breathe" - instant fixed emergency reply
- "What's the weather like?" - fixed refusal, no model call

## Evaluation

```bash
python eval.py
```

Eight fixed cases run directly against the pipeline: two grounded answers, one out-of-scope refusal, two emergency phrasings, routine and same-day classification (checking for false positives), and a full booking flow that verifies a slot is actually consumed in MySQL. Requires MySQL and Ollama to be running.

## Layout

```
app.py            Flask routes, /media-stream WebSocket, turn handling
pipeline.py       STT, LLM (FAQ and booking paths), TTS, model warm-up
safety.py         emergency patterns and urgency classification
rag.py            embedding and FAISS retrieval
db.py             MySQL access: availability and booking
log_utils.py      logging plus the pub/sub feed behind /events
config.py         environment loading
eval.py           fixed eval set
schema.sql        patients, slots, bookings
knowledge_base/   eight mock practice documents used for retrieval
static/call.html  browser call page with live transcript
```

## Known limitations

- **Small-model tool eagerness.** `llama3.2:3b` sometimes calls `book_appointment` on the first ambiguous turn with empty arguments despite instructions not to. It is safe, because `db.book_appointment()` rejects invalid input and the model recovers by asking what is missing, but it is not polished. `phi3:mini` was tried first and does not support Ollama tool-calling at all.
- **Turn detection is a volume threshold**, not a real voice-activity detector, so noisy rooms can cut turns early or late.
- **TTS runs on CPU** (the default `pip install TTS` pulls a CPU-only PyTorch), so replies take a moment.
- **The FAQ path is stateless** across turns; only booking keeps conversation history.
- **Demo scope:** synthetic data, no authentication, Flask's development server.
