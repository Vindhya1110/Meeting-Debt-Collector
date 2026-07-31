import os
import json
from groq import Groq
from prompts import RESOLUTION_PROMPT
from models import get_agent_now
from mock_responses import MOCK_RESOLUTION
from extractor import _parse_json_list

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

# Fallback calendar for demo — used if Google Calendar isn't available
DEMO_CALENDAR = [
    {"title": "Client Call", "datetime": "2026-08-05T15:00:00"},
    {"title": "Sprint Review", "datetime": "2026-08-07T11:00:00"},
    {"title": "Friday Demo", "datetime": "2026-08-08T17:00:00"},
]

def resolve_deadlines(commitments: list) -> list:
    """
    Takes extracted commitments, resolves implicit deadlines to ISO timestamps.
    Only processes items that have deadline_clue or explicit_deadline.
    """
    if not commitments:
        return commitments

    if MOCK_MODE:
        return MOCK_RESOLUTION

    needs_resolution = [
        c for c in commitments
        if c.get("deadline_clue") or c.get("explicit_deadline")
    ]

    if not needs_resolution:
        return commitments

    now = get_agent_now()

    try:
        from calendar_agent import get_upcoming_events
        calendar_context = get_upcoming_events() or DEMO_CALENDAR
    except Exception:
        calendar_context = DEMO_CALENDAR

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": RESOLUTION_PROMPT.format(
                    current_datetime=now.isoformat(),
                    calendar_context=json.dumps(calendar_context)
                )
            },
            {
                "role": "user",
                "content": json.dumps(needs_resolution)
            }
        ],
        temperature=0.0,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content
    resolved = _parse_json_list(raw, preferred_key="commitments")

    # Merge resolved back into full list, matched by id
    resolved_map = {r["id"]: r for r in resolved if "id" in r}
    for c in commitments:
        if c["id"] in resolved_map:
            c.update(resolved_map[c["id"]])
        # Set original_deadline once
        if not c.get("original_deadline") and c.get("deadline"):
            c["original_deadline"] = c["deadline"]

    return commitments
