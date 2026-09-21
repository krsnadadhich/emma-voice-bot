import re

from log_utils import log

# Deterministic, pre-LLM red-flag check. Matched independently of anything the LLM would say —
# this is the clinical safety net, so it must never depend on model behavior being "good enough."
EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. Please hang up and call nine nine nine "
    "immediately, or go to your nearest A and E department."
)

EMERGENCY_PATTERNS = [
    r"\bchest pain\b",
    r"\bcan'?t breathe\b",
    r"\bdifficulty breathing\b",
    r"\b(stopped|not) breathing\b",
    r"\bunresponsive\b",
    r"\bunconscious\b",
    r"\bwon'?t wake up\b",
    r"\bsevere(ly)? bleeding\b",
    r"\bbleeding (heavily|a lot|won'?t stop)\b",
    r"\bstroke\b",
    r"\bface (is |looks )?droop",
    r"\bslurred speech\b",
    r"\bsuicidal\b",
    r"\b(kill|end) (myself|my life)\b",
    r"\bself[- ]harm\b",
    r"\banaphylaxis\b",
    r"\bthroat (is )?(closing|swelling)\b",
    r"\bchoking\b",
    r"\bseizure\b",
    r"\bfitting\b",
    r"\bsevere head injury\b",
    r"\boverdose\b",
    r"\bblue lips\b",
    r"\bnon[- ]?responsive\b",
]
_EMERGENCY_RE = [re.compile(p, re.IGNORECASE) for p in EMERGENCY_PATTERNS]

SAME_DAY_KEYWORDS = [
    "fever", "vomiting", "throwing up", "diarrhea", "diarrhoea", "a lot of pain",
    "in pain", "worried", "getting worse", "won't go away", "infection", "swollen",
    "can't keep anything down", "high temperature", "urgent",
]


def is_emergency(text: str) -> bool:
    for pattern in _EMERGENCY_RE:
        if pattern.search(text):
            log("SAFETY", f"RED FLAG matched ('{pattern.pattern}') - routing to emergency message, bypassing LLM")
            return True
    return False


def classify_urgency(text: str) -> str:
    if is_emergency(text):
        return "emergency"
    lowered = text.lower()
    if any(keyword in lowered for keyword in SAME_DAY_KEYWORDS):
        return "same_day"
    return "routine"
