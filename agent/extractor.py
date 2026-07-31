import uuid
from datetime import datetime
from llm import call, parse_json_list
from prompts import EXTRACTION_PROMPT
from mock_mode import MOCK_COMMITMENTS
import os

MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

def extract(transcript: str, attendees: list, meeting_id: str) -> list:
    if not transcript.strip():
        return []

    if MOCK:
        return _stamp(MOCK_COMMITMENTS, meeting_id)

    raw = call(
        system=EXTRACTION_PROMPT.format(
            attendees=", ".join(a.get("name", "?") if isinstance(a, dict) else str(a)
                                for a in attendees) or "Unknown"
        ),
        user=f"TRANSCRIPT:\n{transcript}",
        temperature=0.1,
        max_tokens=3000,
        expect_json=True,
        provider="groq"
    )

    try:
        items = parse_json_list(raw, preferred_key="commitments")
    except Exception as e:
        print(f"[Extractor] parse failed: {e}\nRaw: {raw[:300]}")
        items = []

    # Filter vague intentions
    real = [c for c in items if c.get("owner_type") != "vague_intention"]

    return _stamp(real, meeting_id)

def _stamp(items: list, meeting_id: str) -> list:
    now = datetime.utcnow().isoformat()
    stamped = []
    for c in items:
        c = dict(c)
        c.setdefault("id", str(uuid.uuid4()))
        c["meeting_id"] = meeting_id
        c["owner"] = c.get("owner") or c.get("speaker") or "Unknown"
        c["status"] = "review" if c.get("confidence", 1.0) < 0.8 else "open"
        c["nudge_count"] = 0
        c["created_at"] = now
        c["updated_at"] = now
        stamped.append(c)
    return stamped
