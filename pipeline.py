import audioop
import json

import numpy as np
import ollama
from faster_whisper import WhisperModel

import company
import config
import db
import orders
import rag
from log_utils import log

SYSTEM_PROMPT = (
    f"You are {company.ASSISTANT}, an AI receptionist for {company.COMPANY}, {company.DESCRIPTION}. "
    "Answer briefly and clearly, like a helpful receptionist speaking on the phone. "
    "Answer using ONLY the context provided below the caller's question — never use "
    "outside knowledge, even if you think you know the answer. "
    "Reply with ONLY your own single spoken response to the caller's last message — "
    "one short sentence, at most two. Never write the caller's side of the conversation, "
    "never continue the dialogue yourself, and never include stage directions or labels."
)

NO_MATCH_REPLY = company.REFUSAL

BOOKING_KEYWORDS = [
    "book", "schedule", "reschedule", "rebook", "pick up", "pickup",
    "collect", "arrange", "delivery slot", "available slot",
]

BOOKING_SYSTEM_PROMPT = (
    f"You are {company.ASSISTANT}, an AI receptionist for {company.COMPANY}, {company.DESCRIPTION}, "
    "helping a caller book a delivery or pickup slot. The currently available slots (with their "
    "kind, location and exact ids) are always given to you below — this list is refreshed every "
    "turn, so trust it over anything said earlier in the conversation.\n\n"
    "Do NOT call the book_slot tool unless you already have BOTH of these, taken from what "
    "the caller has actually said: (1) a specific slot id copied from the available-slots list "
    "below, and (2) the caller's name. If either is missing, do not call any tool — just reply in "
    "plain text, either offering some options from the list (ask whether they want a delivery or "
    "a pickup if that is unclear), or asking for whichever piece is missing. Most first messages "
    "from a caller will be missing both, so most of the time you should NOT call the tool yet.\n\n"
    "Once you do have both, call book_slot with that exact slot id. After booking, confirm "
    "the kind of slot, the place, the day and the time back to the caller. Keep each reply to "
    "1-2 short sentences suitable for text-to-speech. Never write the caller's side of the "
    "conversation, never continue the dialogue yourself."
)

BOOKING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "book_slot",
            "description": "Book a delivery or pickup slot for a caller, once they've chosen a slot id and given their name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "The caller's full name."},
                    "slot_id": {"type": "integer", "description": "The id of the slot to book."},
                },
                "required": ["customer_name", "slot_id"],
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


def _execute_tool(name: str, arguments: dict, order_number: str = "") -> dict:
    if name == "book_slot":
        return db.book_slot(
            customer_name=arguments.get("customer_name", "Unknown"),
            slot_id=arguments.get("slot_id"),
            order_number=order_number,
        )
    return {"error": f"unknown tool '{name}'"}


def _order_number_from_call(user_text: str, history: list) -> str:
    # The model garbles spoken digits, so the order number is read from the transcript, not its tool call.
    texts = [user_text] + [m["content"] for m in reversed(history) if m["role"] == "user"]
    return next((n for n in map(orders.extract_order_number, texts) if n), "")


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


def _has_required_args(arguments: dict) -> bool:
    name = str(arguments.get("customer_name") or "").strip()
    return bool(name) and str(arguments.get("slot_id")).strip().isdigit()


def _offer_slots(slots: list) -> str:
    if not slots:
        return f"Sorry, there are no open slots right now. Please contact the {company.COMPANY} customer team."
    options = "; ".join(f"a {s['kind']} at {s['location']} on {s['slot_time']}" for s in slots[:3])
    return f"I can offer {options}. Which would you like, and what name should I book it under?"


def _confirmation(result: dict, customer_name: str) -> str:
    # Spoken from the tool result, not by the model, so the slot and order details are always correct.
    if not result.get("ok"):
        error = result.get("error", "Something went wrong with that booking.")
        return f"{error} {_offer_slots(db.check_slots())}"
    text = f"You're booked, {customer_name}: a {result['kind']} at {result['location']} on {result['slot_time']}."
    if result.get("linked_order"):
        text += f" It's linked to order {result['linked_order']}."
    return text


def generate_booking_reply(user_text: str, history: list):
    """Returns (reply, booked), where booked is True once a slot was actually booked this turn."""
    slots = db.check_slots()
    system_prompt = f"{BOOKING_SYSTEM_PROMPT}\n\nCurrently available slots: {json.dumps(slots, default=str)}"
    messages = [{"role": "system", "content": system_prompt}] + history + [
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
    complete_calls = [c for c in tool_calls or [] if _has_required_args(c["function"]["arguments"])]
    booked = False

    if tool_calls and not complete_calls:
        log("TOOL", "ignored a book_slot call with no name or slot id; offering the open slots instead")
        reply = _offer_slots(slots)
    elif not tool_calls:
        reply = (msg.get("content") or "").strip()
    else:
        replies = []
        for call in complete_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]
            log("TOOL", f"{fn_name}({fn_args})")
            result = _execute_tool(fn_name, fn_args, _order_number_from_call(user_text, history))
            booked = booked or bool(result.get("ok"))
            replies.append(_confirmation(result, str(fn_args["customer_name"]).strip()))
        reply = " ".join(replies)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    log("REPLY", reply)
    return reply, booked


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
    log("WARMUP", "seeding demo slots and orders...")
    db.seed_if_empty()
    log("WARMUP", "building RAG index and pinging the LLM...")
    generate_reply("What are your delivery options?")
    log("WARMUP", "all models ready")
