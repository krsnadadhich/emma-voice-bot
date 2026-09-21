import datetime
import json

import mysql.connector

import company
import config
from log_utils import log

SLOT_FORMAT = "%A %d %B, %I:%M %p"


def get_connection():
    return mysql.connector.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
    )


def seed_if_empty():
    seed_slots_if_empty()
    seed_orders_if_empty()


def seed_slots_if_empty():
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM slots")
        (count,) = cursor.fetchone()
        if count > 0:
            return

        days = []
        day = datetime.date.today() + datetime.timedelta(days=1)
        while len(days) < company.SLOT_DAYS:
            if day.weekday() < 5:
                days.append(day)
            day += datetime.timedelta(days=1)

        rows = []
        for day in days:
            for i, hour in enumerate(company.SLOT_HOURS):
                slot_time = datetime.datetime.combine(day, datetime.time(hour, 0))
                for kind, locations in company.SLOT_KINDS.items():
                    rows.append((kind, locations[i % len(locations)], slot_time))

        cursor.executemany("INSERT INTO slots (kind, location, slot_time) VALUES (%s, %s, %s)", rows)
        conn.commit()

        # Book a few up front so availability isn't unrealistically wide open.
        cursor.execute("SELECT id FROM slots ORDER BY id")
        prebooked = [row[0] for row in cursor.fetchall()][::6]
        placeholders = ",".join(["%s"] * len(prebooked))
        cursor.execute(f"UPDATE slots SET is_booked = TRUE WHERE id IN ({placeholders})", prebooked)
        conn.commit()

        log("DB", f"seeded {len(rows)} synthetic slots across {len(days)} weekdays")


def seed_orders_if_empty():
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM orders")
        (count,) = cursor.fetchone()
        if count > 0:
            return

        with open(company.ORDERS_FILE, encoding="utf-8") as f:
            orders = json.load(f)

        now = datetime.datetime.now().replace(microsecond=0)
        base = now.replace(minute=0, second=0)
        rows = [
            (
                o["order_number"],
                o["customer_name"],
                o["status"],
                o["city"],
                base + datetime.timedelta(hours=o["eta_start_hours"]),
                base + datetime.timedelta(hours=o["eta_end_hours"]),
                now,
                o["note"],
            )
            for o in orders
        ]
        cursor.executemany(
            "INSERT INTO orders (order_number, customer_name, status, city, eta_start, eta_end, last_update, note) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        conn.commit()
        log("DB", f"seeded {len(rows)} sample orders")


def get_order(order_number: str):
    with get_connection() as conn, conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM orders WHERE order_number = %s", (order_number,))
        return cursor.fetchone()


def check_slots(per_kind: int = 3):
    """Next open slots, a few of each kind (delivery, pickup), soonest first."""
    slots = []
    with get_connection() as conn, conn.cursor(dictionary=True) as cursor:
        for kind in company.SLOT_KINDS:
            cursor.execute(
                "SELECT id, kind, location, slot_time FROM slots "
                "WHERE is_booked = FALSE AND kind = %s AND slot_time > NOW() "
                "ORDER BY slot_time ASC LIMIT %s",
                (kind, per_kind),
            )
            slots.extend(cursor.fetchall())

    slots.sort(key=lambda s: s["slot_time"])
    for slot in slots:
        slot["slot_time"] = slot["slot_time"].strftime(SLOT_FORMAT)
    return slots


def book_slot(customer_name: str, slot_id: int, order_number: str = ""):
    digits = "".join(ch for ch in str(order_number or "") if ch.isdigit())
    linked_order = digits if len(digits) == 6 else None

    with get_connection() as conn, conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT kind, location, slot_time, is_booked FROM slots WHERE id = %s", (slot_id,))
        slot = cursor.fetchone()
        if slot is None:
            return {"ok": False, "error": "That slot doesn't exist."}
        if slot["is_booked"]:
            return {"ok": False, "error": "That slot has already been booked, please choose another."}

        if linked_order:
            cursor.execute("SELECT 1 FROM orders WHERE order_number = %s", (linked_order,))
            if cursor.fetchone() is None:
                linked_order = None

        cursor.execute("UPDATE slots SET is_booked = TRUE WHERE id = %s", (slot_id,))
        cursor.execute(
            "INSERT INTO bookings (customer_name, slot_id, order_number) VALUES (%s, %s, %s)",
            (customer_name, slot_id, linked_order),
        )
        conn.commit()

        when = slot["slot_time"].strftime(SLOT_FORMAT)
        log("DB", f"booked {slot['kind']} slot {slot_id} ({when}) for '{customer_name}'")
        result = {"ok": True, "kind": slot["kind"], "location": slot["location"], "slot_time": when}
        if linked_order:
            result["linked_order"] = " ".join(linked_order)
        return result
