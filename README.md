# EMMA — AI Voice Receptionist

A configurable voice receptionist for a company. Callers talk to it over a live call in the browser; it tells them where their order is, books delivery or pickup slots, and answers questions about the company. Speech-to-text, the LLM and text-to-speech all run locally. The only external service is Twilio, which carries the call audio and does no processing.

Everything company-specific lives in a **profile folder**, so the same code can front any business. The included sample is **Deliverail**, a fictional parcel delivery company.

## The idea worth reading first

Facts never come from the model's memory. Each kind of answer has its own source:

| Caller wants | Answered by | LLM involved? |
|---|---|---|
| Order status | Looked up in MySQL by the six-digit order number and spoken from a template | No |
| A company fact (hours, pricing, service area, policies) | Retrieved from the profile's knowledge documents; if nothing matches closely enough, a fixed refusal | Only when grounded |
| A delivery or pickup slot | Live slots injected into the prompt; the model picks a slot and a name, code validates and books it | For conversation only |

Two details make this hold up with a small local model:
- **Grounding gate.** If retrieval finds nothing above the similarity threshold, the bot returns the profile's refusal without calling the LLM, so it cannot invent an answer it has no source for.
- **Confirmations are spoken from the database result**, and the order number is read from the caller's transcript in code. A 3B model garbled spoken digits and misreported bookings, so it is never trusted with them.

## How a turn works

```
browser (Twilio Voice JS SDK, WebRTC)
   -> Twilio -> Media Stream WebSocket -> Flask /media-stream
        1. buffer audio until ~1.2 s of silence
        2. speech-to-text        faster-whisper (base.en, CPU, int8)
        3. route the turn
             booking in progress or booking intent -> LLM with a book_slot tool, DB-backed confirmation
             order question or an order number     -> orders.py: DB lookup, templated reply
             anything else                         -> RAG over the profile knowledge, or the refusal
        4. text-to-speech        Coqui TTS (Tacotron2-DDC), resampled to 8 kHz mu-law
   <- audio streamed back over the same WebSocket
```

The call page also shows a live transcript panel, fed by Server-Sent Events from the same log lines the server prints.

## Company profiles

A profile is a folder under `profiles/`, selected with `COMPANY_PROFILE` in `.env` (default `deliverail`):

```
profiles/deliverail/
  profile.json     company name, assistant name, greeting, refusal message, slot kinds and locations, slot hours
  knowledge/*.txt  the documents the bot answers from
  orders.json      sample orders seeded into MySQL (status, city, ETA offsets)
```

To adapt it to another company, copy the folder, edit the three parts, and point `COMPANY_PROFILE` at it. The slot kinds in `profile.json` (for example `delivery` and `pickup`) and their locations control what can be booked. For a real system, replace `db.get_order` with a call to your order or tracking system.

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
3. **Database:** create a database called `emma_demo` and apply `schema.sql`. Applying it drops and recreates the demo tables, so re-run it any time you want to reset the data. Slots and sample orders are seeded automatically at startup.
   On Windows, keep the MySQL data directory at a plain path such as `C:\mysql-data`; a nested or dot-prefixed directory triggered an InnoDB startup error in my setup.
4. **Twilio:** create an API key and a TwiML Application whose Voice request URL is `https://<your-ngrok-domain>/webhook/voice`.
5. **Config:** copy `.env.example` to `.env` and fill in the Twilio Account SID, API key, API secret and TwiML App SID.

## Run

```bash
python app.py                # loads all models, then serves on :5000
ngrok http 5000              # public HTTPS/WSS URL for Twilio
```

Open `http://localhost:5000/static/call.html`, wait for **ready**, and click **Call EMMA**.

Things to try with the Deliverail sample:

- "Where is my order four eight two nine one three?" - status and delivery window from the database
- "I'd like to book a pickup" - multi-turn booking, optionally linked to an order number
- "What are your delivery options?" or "How much does it cost to send a small parcel?" - grounded answers
- "What's the weather like?" - fixed refusal, no model call

Sample order numbers are in `profiles/deliverail/orders.json` (for example 482913 out for delivery, 128374 delivery failed, 905531 delayed).

## Evaluation

```bash
python eval.py
```

Eight fixed cases run directly against the code: two grounded answers, one out-of-scope refusal, a known order, an unknown order, the missing-number prompt, spoken-digit parsing, and a full booking that verifies a slot is consumed in MySQL. Requires MySQL and Ollama to be running.

## Layout

```
app.py            Flask routes, /media-stream WebSocket, turn routing
pipeline.py       STT, FAQ and booking LLM paths, TTS, model warm-up
orders.py         order-number parsing, status lookup and spoken templates
rag.py            embedding and FAISS retrieval over the profile's knowledge
db.py             MySQL access: orders, slot availability, booking
company.py        loads the selected profile
log_utils.py      logging plus the pub/sub feed behind /events
config.py         environment loading
eval.py           fixed eval set
schema.sql        orders, slots, bookings
profiles/         company profiles (sample: deliverail)
static/call.html  browser call page with live transcript
``

## Known limitations

- **Spoken order numbers depend on Whisper.** Digits are normalised in code (words, groups, "oh" as zero), but a mis-heard digit means a not-found result. The bot asks again up to twice before pointing the caller to the customer team.
- **Small-model tool eagerness.** `llama3.2:3b` often calls `book_slot` on the first ambiguous turn with empty arguments. Those calls are ignored and the reply is built from the open slots instead.
- **Turn detection is a volume threshold**, not a real voice-activity detector, so noisy rooms can cut turns early or late.
- **TTS runs on CPU** (the default `pip install TTS` pulls a CPU-only PyTorch), so replies take a moment.
- **The FAQ path is stateless** across turns; only booking keeps conversation history.
- **Demo scope:** synthetic data, no authentication, no human hand-off, Flask's development server.

## License

MIT. See [LICENSE](LICENSE). Contributions and issues are welcome.
