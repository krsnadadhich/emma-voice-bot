import json
import os

import config

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "profiles", config.COMPANY_PROFILE)

with open(os.path.join(PROFILE_DIR, "profile.json"), encoding="utf-8") as f:
    _profile = json.load(f)

COMPANY = _profile["company"]
ASSISTANT = _profile["assistant"]
DESCRIPTION = _profile["description"]
GREETING = _profile["greeting"]
REFUSAL = _profile["refusal"]
SLOT_KINDS = _profile["slot_kinds"]
SLOT_HOURS = _profile["slot_hours"]
SLOT_DAYS = _profile["slot_days"]

KNOWLEDGE_DIR = os.path.join(PROFILE_DIR, "knowledge")
ORDERS_FILE = os.path.join(PROFILE_DIR, "orders.json")
