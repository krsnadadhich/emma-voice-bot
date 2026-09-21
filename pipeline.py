import audioop
import json

import numpy as np
import ollama
from faster_whisper import WhisperModel

import config
import db
import rag
from log_utils import log

SYSTEM_PROMPT = (
    "You are EMMA, an AI reception assistant for a GP surgery in England. "
    "Answer briefly and clearly, like a helpful receptionist speaking on the phone. "
    "Answer using ONLY the context provided below the caller's question — never use "
    "outside knowledge, even if you think you know the answer. "
    "Reply with ONLY your own single spoken response to the caller's last message — "
    "one short sentence, at most two. Never write the caller's side of the conversation, "
    "never continue the dialogue yourself, and never include stage directions or labels."
)

NO_MATCH_REPLY = (
    "I'm sorry, I don't have that information. Please call the surgery directly "
    "and our team will be happy to help."
)

BOOKING_KEYWORDS = [
    "book", "appointment", "schedule", "reschedule", "available slot",
    "see a doctor", "see the doctor", "see a gp",
]

BOOKING_SYSTEM_PROMPT = (
    "You are EMMA, an AI reception assistant for a GP surgery in England, helping a caller book "
    "an appointment. The currently available slots (with their exact ids) are always given to you "
    "below — this list is refreshed every turn, so trust it over anything said earlier in the "
    "conversation.\n\n"
    "Do NOT call the book_appointment tool unless you already have BOTH of these, taken from what "
    "the caller has actually said: (1) a specific slot id copied from the available-slots list "
    "below, and (2) the caller's name. If either is missing, do not call any tool — just reply in "
    "plain text, either offering some options from the list, or asking for whichever piece is "
    "missing. Most first messages from a caller will be missing both, so most of the time you "
    "should NOT call the tool yet.\n\n"
    "Once you do have both, call book_appointment with that exact slot id. After booking, confirm "
    "the day, time, and clinician back to the caller. Keep each reply to 1-2 short sentences "
    "suitable for text-to-speech. Never write the caller's side of the conversation, never continue "
    "the dialogue yourself."
)


BOOKING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a specific appointment slot for a patient, once they've chosen a slot id and given their name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "The caller's full name."},
                    "slot_id": {"type": "integer", "description": "The id of the slot to book."},
                    "reason": {"type": "string", "description": "Brief reason for the visit, if given."},
                },
                "required": ["patient_name", "slot_id"],
            },
        },
    },
]

_whisper_model = None
_tts_model = None
_ollama_client = ollama.Client(host=config.OLLAMA_HOST)


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        # CPU + int8: leaves the GPU's 4GB VRAM free for Ollama's LLM and Coqui TTS.
        _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _whisper_model


def transcribe(pcm16_16k: bytes) -> str:
    audio = np.frombuffer(pcm16_16k, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = get_whisper_model().transcribe(audio, language="en")
    text = " ".join(segment.text for segment in segments).strip()
    log("TRANSCRIPT", text or "(empty)")
    return text


def is_booking_request(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in BOOKING_KEYWORDS)


def _execute_tool(name: str, arguments: dict) -> dict:
    if name == "book_appointment":
        return db.book_appointment(
            patient_name=arguments.get("patient_name", "Unknown"),
            slot_id=arguments.get("slot_id"),
            reason=arguments.get("reason", ""),
        )
    return {"error": f"unknown tool '{name}'"}


def generate_reply(user_text: str) -> str:
    matches = rag.retrieve(user_text)
    if not matches:
        log("RAG", "no match above threshold - refusing without calling the LLM")
        log("REPLY", NO_MATCH_REPLY)
        return NO_MATCH_REPLY

    log("RAG", f"matched {[name for name, _, _ in matches]} (top score {matches[0][2]:.2f})")
    context = "\n\n".join(f"[{name}]\n{text}" for name, text, _ in matches)
    user_message = f"Context:\n{context}\n\nCaller's question: {user_text}"

    response = _ollama_client.chat(
        model=config.OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        options={"num_predict": 60, "temperature": 0.4},
        keep_alive="30m",
    )
    reply = response["message"]["content"].strip()
    log("REPLY", reply)
    return reply


def _booking_system_prompt_with_availability() -> str:
    slots = db.check_availability()
    return f"{BOOKING_SYSTEM_PROMPT}\n\nCurrently available slots: {json.dumps(slots, default=str)}"


def generate_booking_reply(user_text: str, history: list) -> str:
    messages = [{"role": "system", "content": _booking_system_prompt_with_availability()}] + history + [
        {"role": "user", "content": user_text}
    ]

    response = _ollama_client.chat(
        model=config.OLLAMA_MODEL,
        messages=messages,
        tools=BOOKING_TOOLS,
        options={"num_predict": 150, "temperature": 0.1},
        keep_alive="30m",
    )
    msg = response["message"]
    tool_calls = msg.get("tool_calls")

    if not tool_calls:
        reply = (msg.get("content") or "").strip()
    else:
        messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": tool_calls})
        for call in tool_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]
            log("TOOL", f"{fn_name}({fn_args})")
            result = _execute_tool(fn_name, fn_args)
            messages.append({"role": "tool", "content": json.dumps(result, default=str)})

        messages.append({
            "role": "user",
            "content": (
                "Using the tool result above, reply to the caller now in plain spoken English — "
                "1-2 short sentences, no JSON, no tool-call syntax, no field names."
            ),
        })
        followup = _ollama_client.chat(
            model=config.OLLAMA_MODEL,
            messages=messages,
            options={"num_predict": 80, "temperature": 0.3},
            keep_alive="30m",
        )
        reply = followup["message"]["content"].strip()

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    log("REPLY", reply)
    return reply


def get_tts_model():
    global _tts_model
    if _tts_model is None:
        import torch
        from TTS.api import TTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _tts_model = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False).to(device)
    return _tts_model


def synthesize(text: str) -> bytes:
    """Returns 8kHz 8-bit mu-law audio, the format Twilio Media Streams expects back."""
    wav = get_tts_model().tts(text)
    pcm16 = (np.array(wav, dtype=np.float32) * 32767).astype(np.int16).tobytes()
    pcm16_8k, _ = audioop.ratecv(pcm16, 2, 1, 22050, 8000, None)
    return audioop.lin2ulaw(pcm16_8k, 2)


def warm_up():
    """Loads/downloads every model once at startup so the first real call isn't stalled mid-turn."""
    log("WARMUP", "loading faster-whisper...")
    get_whisper_model()
    log("WARMUP", "loading Coqui TTS...")
    get_tts_model()
    log("WARMUP", "seeding synthetic booking slots...")
    db.seed_slots_if_empty()
    log("WARMUP", "building RAG index and pinging the LLM...")
    generate_reply("What are your opening hours?")
    log("WARMUP", "all models ready")
