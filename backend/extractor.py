import os
import json
import uuid
from datetime import datetime
from groq import Groq
from prompts import EXTRACTION_PROMPT
from mock_responses import MOCK_EXTRACTION

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

def extract_commitments(transcript: str, attendees: list, meeting_id: str) -> list:
    """
    Send transcript to Groq LLM, get back structured commitment list.
    Filters out vague_intention items automatically.
    Assigns IDs and meeting_id to each commitment.
    """
    if not transcript or not transcript.strip():
        return []

    if MOCK_MODE:
        return _inject_ids(MOCK_EXTRACTION, meeting_id)

    prompt = EXTRACTION_PROMPT.format(
        attendees=", ".join([a["name"] for a in attendees]) if attendees else "Unknown"
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"TRANSCRIPT:\n{transcript}"}
        ],
        temperature=0.1,   # low temp for structured extraction
        max_tokens=2000,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content
    items = _parse_json_list(raw, preferred_key="commitments")

    # Filter vague intentions — agent decides what NOT to track
    real_commitments = [
        item for item in items
        if item.get("owner_type") != "vague_intention"
    ]

    return _inject_ids(real_commitments, meeting_id)

def _parse_json_list(raw: str, preferred_key: str = None) -> list:
    """Robustly pull a list out of an LLM JSON response, whatever shape it comes in."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if preferred_key and preferred_key in parsed:
            return parsed[preferred_key]
        for v in parsed.values():
            if isinstance(v, list):
                return v
    return []

def _inject_ids(items: list, meeting_id: str) -> list:
    now = datetime.utcnow().isoformat()
    for item in items:
        item["id"] = str(uuid.uuid4())
        item["meeting_id"] = meeting_id
        item["owner"] = item.get("speaker") or item.get("owner") or "Unknown"
        item["status"] = "open"
        item["nudge_count"] = 0
        item["created_at"] = now
        item["updated_at"] = now
    return items
