import datetime

import mysql.connector

import config
from log_utils import log

CLINICIANS = ["Dr. Patel", "Dr. Osei", "Dr. Whitfield"]
SLOT_HOURS = [9, 10, 11, 14, 15, 16]


def get_connection():
    return mysql.connector.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
    )


def seed_slots_if_empty():
    """Populates the next 5 weekdays with synthetic appointment slots, a few pre-booked."""
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM slots")
        (count,) = cursor.fetchone()
        if count > 0:
            return

        today = datetime.date.today()
        days = []
        d = today + datetime.timedelta(days=1)
        while len(days) < 5:
            if d.weekday() < 5:  # Mon-Fri
                days.append(d)
            d += datetime.timedelta(days=1)

        rows = []
        for day in days:
            for i, hour in enumerate(SLOT_HOURS):
                clinician = CLINICIANS[i % len(CLINICIANS)]
                slot_time = datetime.datetime.combine(day, datetime.time(hour, 0))
                rows.append((clinician, slot_time))

        cursor.executemany(
            "INSERT INTO slots (clinician_name, slot_time, is_booked) VALUES (%s, %s, FALSE)",
            rows,
        )
        conn.commit()

        # Pre-book a handful of slots so availability isn't unrealistically wide open.
        cursor.execute("SELECT id FROM slots ORDER BY id LIMIT 5")
        ids_to_prebook = [row[0] for row in cursor.fetchall()][::2]
        if ids_to_prebook:
            placeholders = ",".join(["%s"] * len(ids_to_prebook))
            cursor.execute(f"UPDATE slots SET is_booked = TRUE WHERE id IN ({placeholders})", ids_to_prebook)
            conn.commit()

        log("DB", f"seeded {len(rows)} synthetic slots across {len(days)} weekdays")


def check_availability(max_results: int = 5):
    """Returns the next available (unbooked) slots as a list of dicts."""
    with get_connection() as conn, conn.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT id, clinician_name, slot_time FROM slots "
            "WHERE is_booked = FALSE AND slot_time > NOW() "
            "ORDER BY slot_time ASC LIMIT %s",
            (max_results,),
        )
        slots = cursor.fetchall()

    for slot in slots:
        slot["slot_time"] = slot["slot_time"].strftime("%A %d %B, %I:%M %p")
    return slots


def book_appointment(patient_name: str, slot_id: int, reason: str = ""):
    """Books a slot for a (newly created) patient. Returns a result dict with ok/error."""
    with get_connection() as conn, conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT is_booked, clinician_name, slot_time FROM slots WHERE id = %s", (slot_id,))
        slot = cursor.fetchone()
        if slot is None:
            return {"ok": False, "error": "That slot doesn't exist."}
        if slot["is_booked"]:
            return {"ok": False, "error": "That slot has already been booked, please choose another."}

        cursor.execute("INSERT INTO patients (full_name) VALUES (%s)", (patient_name,))
        patient_id = cursor.lastrowid

        cursor.execute("UPDATE slots SET is_booked = TRUE WHERE id = %s", (slot_id,))
        cursor.execute(
            "INSERT INTO bookings (patient_id, slot_id, reason) VALUES (%s, %s, %s)",
            (patient_id, slot_id, reason),
        )
        conn.commit()

        log("DB", f"booked slot {slot_id} ({slot['slot_time']}) for '{patient_name}'")
        return {
            "ok": True,
            "clinician_name": slot["clinician_name"],
            "slot_time": slot["slot_time"].strftime("%A %d %B, %I:%M %p"),
        }
