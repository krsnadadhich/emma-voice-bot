import base64
import json
import queue

from flask import Flask, Response, request
from flask_sock import Sock
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import Connect, VoiceResponse
import audioop
import company
import config
import log_utils
import orders
import pipeline

app = Flask(__name__)
sock = Sock(app)

SILENCE_RMS_THRESHOLD = 500
SILENCE_FRAMES_TO_TRIGGER = 60  # ~60 * 20ms = 1.2s of silence ends a turn


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/profile")
def profile():
    return {"company": company.COMPANY, "assistant": company.ASSISTANT}


@app.get("/events")
def events():
    """Server-Sent Events feed of the same log lines printed to the console — powers call.html's
    live transcript panel."""
    def stream():
        q = log_utils.subscribe()
        try:
            while True:
                try:
                    line = q.get(timeout=15)
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            log_utils.unsubscribe(q)

    return Response(stream(), mimetype="text/event-stream")


@app.get("/token")
def token():
    """Mints an Access Token so static/call.html can place a browser call — no purchased phone number needed."""
    access_token = AccessToken(
        config.TWILIO_ACCOUNT_SID,
        config.TWILIO_API_KEY,
        config.TWILIO_API_SECRET,
        identity="krishna-demo",
    )
    access_token.add_grant(VoiceGrant(outgoing_application_sid=config.TWILIO_TWIML_APP_SID))
    return {"token": access_token.to_jwt()}


@app.post("/webhook/voice")
def voice_webhook():
    """Twilio hits this when a call comes in, whether from call.html or a real number."""
    response = VoiceResponse()
    response.say(company.GREETING)
    connect = Connect()
    connect.stream(url=f"wss://{request.host}/media-stream")
    response.append(connect)
    return str(response), 200, {"Content-Type": "text/xml"}


@sock.route("/media-stream")
def media_stream(ws):
    """Handles Twilio's bidirectional Media Streams protocol for one call."""
    stream_sid = None
    audio_buffer = bytearray()
    silence_count = 0
    speaking = False
    booking_history = []  # only used once a booking request is detected, for slot-filling across turns
    booking_active = False
    awaiting_order = False
    order_attempts = 0

    def handle_turn(mulaw_bytes):
        nonlocal booking_active, awaiting_order, order_attempts
        try:
            pcm16_8k = audioop.ulaw2lin(mulaw_bytes, 2)
            pcm16_16k, _ = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, None)

            text = pipeline.transcribe(pcm16_16k)
            if not text:
                return

            if booking_active or pipeline.is_booking_request(text):
                reply, booked = pipeline.generate_booking_reply(text, booking_history)
                booking_active = not booked
                if booked:
                    booking_history.clear()
            elif awaiting_order or orders.is_order_query(text) or orders.extract_order_number(text):
                # Order status comes straight from the database; the LLM is never called on this path.
                reply, awaiting_order, order_attempts = orders.handle(text, order_attempts)
            else:
                reply = pipeline.generate_reply(text)

            send_audio(ws, stream_sid, pipeline.synthesize(reply))
        except Exception as e:
            pipeline.log("ERROR", f"{type(e).__name__}: {e}")

    while True:
        raw = ws.receive()
        if raw is None:
            break
        msg = json.loads(raw)
        event = msg.get("event")

        if event == "start":
            stream_sid = msg["start"]["streamSid"]
            pipeline.log("CALL", f"stream started ({stream_sid})")

        elif event == "media":
            payload = base64.b64decode(msg["media"]["payload"])
            audio_buffer.extend(payload)

            pcm16 = audioop.ulaw2lin(payload, 2)
            rms = audioop.rms(pcm16, 2)

            if rms > SILENCE_RMS_THRESHOLD:
                speaking = True
                silence_count = 0
            elif speaking:
                silence_count += 1
                if silence_count > SILENCE_FRAMES_TO_TRIGGER:
                    handle_turn(bytes(audio_buffer))
                    audio_buffer = bytearray()
                    speaking = False
                    silence_count = 0

        elif event == "stop":
            pipeline.log("CALL", "stream stopped")
            break


def send_audio(ws, stream_sid, mulaw_bytes):
    chunk_size = 160  # 20ms of audio @ 8kHz mu-law
    for i in range(0, len(mulaw_bytes), chunk_size):
        chunk = mulaw_bytes[i:i + chunk_size]
        payload = base64.b64encode(chunk).decode("ascii")
        ws.send(json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload},
        }))


if __name__ == "__main__":
    pipeline.warm_up()
    app.run(host="0.0.0.0", port=config.PORT, debug=True, use_reloader=False, threaded=True)
