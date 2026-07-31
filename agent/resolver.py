import json
import re
from datetime import timedelta
from llm import call, parse_json_list
from prompts import RESOLUTION_PROMPT
from models import get_agent_now

DEMO_CALENDAR = [
    {"title": "Client Call", "datetime": "2026-08-05T15:00:00"},
    {"title": "Sprint Review", "datetime": "2026-08-07T11:00:00"},
    {"title": "Friday Demo", "datetime": "2026-08-08T17:00:00"},
]

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}
TIME_OF_DAY = [
    ("end of day", 18, 0), ("morning", 9, 0), ("noon", 12, 0),
    ("afternoon", 15, 0), ("evening", 18, 0), ("night", 20, 0),
]

def _fallback_resolve(phrase: str, now) -> str:
    """
    Deterministic backstop for the same rules RESOLUTION_PROMPT already
    specifies. Used only when the LLM's response omits a deadline for a
    commitment that clearly had an explicit deadline phrase — LLM JSON
    responses aren't 100% reliable at including every item every time.
    """
    if not phrase:
        return None
    p = phrase.lower()

    hour, minute = 18, 0
    for kw, h, m in TIME_OF_DAY:
        if kw in p:
            hour, minute = h, m
            break

    if "asap" in p or "soon" in p:
        return (now + timedelta(hours=24)).isoformat()
    if "end of week" in p:
        days_ahead = (4 - now.weekday()) % 7 or 7
        target = now + timedelta(days=days_ahead)
        return target.replace(hour=18, minute=0, second=0, microsecond=0).isoformat()
    if "next week" in p:
        days_ahead = (0 - now.weekday()) % 7 or 7
        target = now + timedelta(days=days_ahead)
        return target.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()

    for name, idx in WEEKDAYS.items():
        if name in p:
            days_ahead = (idx - now.weekday()) % 7 or 7
            target = now + timedelta(days=days_ahead)
            return target.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    if "today" in p or "end of day" in p:
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    return None

def resolve(commitments: list, calendar: list = None) -> list:
    needs = [c for c in commitments
             if c.get("deadline_clue") or c.get("explicit_deadline")]
    if not needs:
        return commitments

    if calendar is None:
        try:
            from calendar_agent import get_upcoming_events
            calendar = get_upcoming_events() or DEMO_CALENDAR
        except Exception:
            calendar = DEMO_CALENDAR

    raw = call(
        system=RESOLUTION_PROMPT.format(
            current_datetime=get_agent_now().isoformat(),
            calendar_json=json.dumps(calendar),
            commitments_json=json.dumps(needs)
        ),
        user="Resolve the deadlines.",
        temperature=0.0,
        max_tokens=2000,
        expect_json=True,
        provider="groq"
    )

    try:
        resolved = parse_json_list(raw, preferred_key="commitments")
        rmap = {r["id"]: r for r in resolved if "id" in r}
        for c in commitments:
            if c["id"] in rmap:
                c.update(rmap[c["id"]])
    except Exception as e:
        print(f"[Resolver] failed: {e}")

    now = get_agent_now()
    for c in commitments:
        if not c.get("deadline") and (c.get("explicit_deadline") or c.get("deadline_clue")):
            fallback = _fallback_resolve(c.get("explicit_deadline") or c.get("deadline_clue"), now)
            if fallback:
                c["deadline"] = fallback
                print(f"[Resolver] used deterministic fallback for {c.get('id','?')[:8]}: "
                      f"\"{c.get('explicit_deadline') or c.get('deadline_clue')}\" -> {fallback}")
        if not c.get("original_deadline") and c.get("deadline"):
            c["original_deadline"] = c["deadline"]

    return commitments
