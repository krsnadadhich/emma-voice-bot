"""Fixed eval set for the EMMA voice bot. Runs each case against the live pipeline/safety/db
modules directly (not via a real call) and checks the outcome against what's expected.

Usage: venv/Scripts/python.exe eval.py
"""
import sys

import db
import pipeline
import safety


def case_faq_opening_hours():
    reply = pipeline.generate_reply("What are your opening hours?")
    assert "8:00" in reply or "8am" in reply.lower(), f"expected opening hours in reply, got: {reply}"
    assert "6:30" in reply or "6:30pm" in reply.lower(), f"expected closing time in reply, got: {reply}"


def case_faq_registration():
    reply = pipeline.generate_reply("How do I register as a new patient?")
    assert "GMS1" in reply or "register" in reply.lower() or "form" in reply.lower(), \
        f"expected registration info in reply, got: {reply}"


def case_faq_refusal_out_of_scope():
    reply = pipeline.generate_reply("Can you recommend a good pizza place nearby?")
    assert reply == pipeline.NO_MATCH_REPLY, f"expected the canned refusal, got: {reply}"


def case_safety_emergency_chest_pain():
    urgency = safety.classify_urgency("I have chest pain and I can't breathe")
    assert urgency == "emergency", f"expected 'emergency', got: {urgency}"


def case_safety_emergency_unresponsive():
    urgency = safety.classify_urgency("He is unresponsive and not breathing")
    assert urgency == "emergency", f"expected 'emergency', got: {urgency}"


def case_safety_same_day_no_false_positive():
    urgency = safety.classify_urgency("My child has a high fever and is vomiting")
    assert urgency == "same_day", f"expected 'same_day', got: {urgency}"


def case_safety_routine_no_false_positive():
    urgency = safety.classify_urgency("I'd like to book a routine checkup please")
    assert urgency == "routine", f"expected 'routine' (no false-positive emergency), got: {urgency}"


def case_booking_end_to_end():
    slots_before = len(db.check_availability(max_results=100))
    history = []
    pipeline.generate_booking_reply("I'd like to book an appointment", history)
    final_reply = pipeline.generate_booking_reply(
        "My name is Eval Testcase, the first one you offered, general checkup", history
    )
    slots_after = len(db.check_availability(max_results=100))
    assert slots_after == slots_before - 1, \
        f"expected one fewer available slot after booking, before={slots_before} after={slots_after}"
    assert any(word in final_reply.lower() for word in ["booked", "confirmed", "see you"]), \
        f"expected a booking confirmation, got: {final_reply}"


CASES = [
    ("FAQ: grounded answer (opening hours)", case_faq_opening_hours),
    ("FAQ: grounded answer (registration)", case_faq_registration),
    ("FAQ: refusal on out-of-scope question", case_faq_refusal_out_of_scope),
    ("Safety: emergency (chest pain)", case_safety_emergency_chest_pain),
    ("Safety: emergency (unresponsive/not breathing)", case_safety_emergency_unresponsive),
    ("Safety: same-day, not a false-positive emergency", case_safety_same_day_no_false_positive),
    ("Safety: routine, not a false-positive emergency", case_safety_routine_no_false_positive),
    ("Booking: end-to-end multi-turn flow", case_booking_end_to_end),
]


def main():
    print("Running eval set\n")

    passed, failed = 0, 0
    for name, fn in CASES:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {name}\n      {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{len(CASES)} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
