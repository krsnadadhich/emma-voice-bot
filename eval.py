"""Fixed eval set for the receptionist. Runs each case against the live pipeline, orders and db
modules directly (not via a real call) and checks the outcome against what's expected.

Usage: venv/Scripts/python.exe eval.py
"""
import sys

import db
import orders
import pipeline


def case_faq_delivery_options():
    reply = pipeline.generate_reply("What are your delivery options?").lower()
    assert any(word in reply for word in ["next-day", "next day", "same-day", "same day", "standard"]), \
        f"expected delivery options in reply, got: {reply}"


def case_faq_pricing():
    reply = pipeline.generate_reply("How much does it cost to send a small parcel?")
    assert any(ch.isdigit() for ch in reply), f"expected a price in reply, got: {reply}"


def case_faq_refusal_out_of_scope():
    reply = pipeline.generate_reply("Can you recommend a good pizza place nearby?")
    assert reply == pipeline.NO_MATCH_REPLY, f"expected the canned refusal, got: {reply}"


def case_order_known():
    reply, awaiting, _ = orders.handle("Where is my order 482913?", 0)
    assert "out for delivery" in reply and not awaiting, f"expected an out-for-delivery status, got: {reply}"


def case_order_unknown():
    reply, awaiting, _ = orders.handle("Track order 111111 please", 0)
    assert "couldn't find" in reply and awaiting, f"expected a not-found reply that asks again, got: {reply}"


def case_order_number_asked_for():
    reply, awaiting, attempts = orders.handle("Where is my parcel?", 0)
    assert "order number" in reply and awaiting and attempts == 1, f"expected a prompt for the number, got: {reply}"


def case_order_spoken_digits():
    spoken = orders.extract_order_number("my order is four eight two nine one three please")
    grouped = orders.extract_order_number("it's 4 8 2 9 1 3")
    with_oh = orders.extract_order_number("five oh seven two four six")
    assert (spoken, grouped, with_oh) == ("482913", "482913", "507246"), (spoken, grouped, with_oh)


def case_booking_end_to_end():
    slots_before = len(db.check_slots(per_kind=100))
    history = []
    pipeline.generate_booking_reply("I'd like to book a delivery slot", history)
    _, booked = pipeline.generate_booking_reply(
        "My name is Eval Testcase, the first delivery slot you offered", history
    )
    slots_after = len(db.check_slots(per_kind=100))
    assert booked and slots_after == slots_before - 1, \
        f"expected one booked slot, booked={booked} before={slots_before} after={slots_after}"


CASES = [
    ("FAQ: grounded answer (delivery options)", case_faq_delivery_options),
    ("FAQ: grounded answer (pricing)", case_faq_pricing),
    ("FAQ: refusal on out-of-scope question", case_faq_refusal_out_of_scope),
    ("Order: known order number", case_order_known),
    ("Order: unknown order number", case_order_unknown),
    ("Order: asks for the number when missing", case_order_number_asked_for),
    ("Order: spoken digit formats", case_order_spoken_digits),
    ("Booking: end-to-end multi-turn flow", case_booking_end_to_end),
]


def main():
    print("Running eval set\n")
    db.seed_if_empty()

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
