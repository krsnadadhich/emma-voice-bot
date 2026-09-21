import datetime
import re

import company
import db
from log_utils import log

ORDER_LENGTH = 6
MAX_ASKS = 3

NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

ORDER_QUERY = re.compile(
    r"\b(where(?:'s| is| are)? my|track(?:ing)?|status of|my (?:order|parcel|package|delivery)"
    r"|when (?:will|is|does) my|order status|delivery status)\b"
)
HOW_TO = re.compile(r"\bhow (?:do|can|to|does|would)\b")


def is_order_query(text: str) -> bool:
    lowered = text.lower()
    return not HOW_TO.search(lowered) and bool(ORDER_QUERY.search(lowered))


def extract_order_number(text: str):
    runs, current = [], ""
    for token in re.findall(r"[a-z]+|\d+", text.lower()):
        if token.isdigit():
            current += token
        elif token in NUMBER_WORDS:
            current += NUMBER_WORDS[token]
        elif token == "oh" and current:
            current += "0"
        else:
            if current:
                runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return next((run for run in runs if len(run) == ORDER_LENGTH), None)


def spoken_number(order_number: str) -> str:
    return " ".join(order_number)


def _time(dt: datetime.datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _day(dt: datetime.datetime, now: datetime.datetime) -> str:
    offset = (dt.date() - now.date()).days
    return {0: "today", 1: "tomorrow", -1: "yesterday"}.get(offset, dt.strftime("%A %d %B"))


def _window(start, end, now) -> str:
    if start is None or end is None:
        return "soon"
    if start == end:
        return f"{_day(start, now)} at {_time(start)}"
    if start.date() == end.date():
        return f"{_day(start, now)} between {_time(start)} and {_time(end)}"
    return f"between {_day(start, now)} {_time(start)} and {_day(end, now)} {_time(end)}"


def describe(order: dict, now=None) -> str:
    now = now or datetime.datetime.now()
    number = spoken_number(order["order_number"])
    status = order["status"]
    note = order["note"]
    when = _window(order["eta_start"], order["eta_end"], now)

    if status == "label_created":
        return f"Order {number} is registered and waiting to be collected. Expected delivery {when}."
    if status == "picked_up":
        return f"Order {number} has been picked up and is on its way to our depot. Expected delivery {when}."
    if status == "at_depot":
        return f"Order {number} is at our {order['city']} depot. Expected delivery {when}."
    if status == "out_for_delivery":
        return f"Order {number} is out for delivery in {order['city']}. Expected {when}."
    if status == "delivered":
        text = f"Order {number} was delivered {_day(order['eta_start'], now)} at {_time(order['eta_start'])}."
        return f"{text} {note}." if note else text
    if status == "delivery_failed":
        reason = f" because {note}" if note else ""
        return f"We couldn't deliver order {number}{reason}. We'll try again {when}."
    if status == "delayed":
        reason = f" due to {note}" if note else ""
        return f"Order {number} is delayed{reason}. The new estimate is {when}."
    return f"Order {number} is currently {status.replace('_', ' ')}."


def handle(text: str, attempts: int):
    """Answers an order-status turn from the database. Returns (reply, still_awaiting_number, attempts)."""
    number = extract_order_number(text)
    if number:
        order = db.get_order(number)
        if order:
            log("ORDER", f"{number} found, status {order['status']}")
            reply = describe(order)
            log("REPLY", reply)
            return reply, False, 0
        log("ORDER", f"{number} not found")

    attempts += 1
    if attempts >= MAX_ASKS:
        reply = f"I'm having trouble finding that order. Please contact the {company.COMPANY} customer team."
        log("REPLY", reply)
        return reply, False, 0

    if number:
        reply = f"I couldn't find an order with number {spoken_number(number)}. Please check it and read it out again."
    elif attempts == 1:
        reply = f"Sure, what's your {ORDER_LENGTH}-digit order number?"
    else:
        reply = "I didn't catch a six-digit number. Please read the digits out slowly, one at a time."
    log("REPLY", reply)
    return reply, True, attempts
