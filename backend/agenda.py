import os
import json
import glob
from datetime import datetime
from groq import Groq
from models import get_db
from prompts import AGENDA_SLOT_MATCHING_PROMPT
from extractor import _parse_json_list

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

TEMPLATES = {}

def load_templates():
    """Load all template JSON files from backend/templates/"""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    for path in glob.glob(f"{template_dir}/*.json"):
        with open(path) as f:
            t = json.load(f)
            TEMPLATES[t["type"]] = t

def init_agenda_for_meeting(meeting_id: str, meeting_type: str):
    """Create agenda_state rows for a new meeting based on its type."""
    template = TEMPLATES.get(meeting_type, TEMPLATES.get("club_meeting"))
    if not template:
        return
    conn = get_db()
    for slot in template["slots"]:
        conn.execute("""
            INSERT OR IGNORE INTO agenda_state
            (meeting_id, slot_id, label, required, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (meeting_id, slot["id"], slot["label"], 1 if slot["required"] else 0))
    conn.commit()
    conn.close()

def process_chunk_for_agenda(meeting_id: str, meeting_type: str, chunk: str, commitments: list):
    """
    Called every time a new transcript chunk arrives.
    Checks which agenda slots the chunk covers.
    Special: "owners" slot is computed from commitments, not LLM-matched.
    """
    if not chunk or not chunk.strip():
        return

    conn = get_db()
    pending_slots = conn.execute("""
        SELECT slot_id, label, required FROM agenda_state
        WHERE meeting_id=? AND status='pending'
    """, (meeting_id,)).fetchall()
    conn.close()

    if not pending_slots:
        return  # All slots covered, nothing to do

    # Special rule: "owners" slot — computed, not LLM-matched
    owners_slot = next((s for s in pending_slots if s["slot_id"] == "owners"), None)
    if owners_slot:
        ownerless = [c for c in commitments if c.get("owner_type") == "ownerless"]
        if not ownerless and commitments:
            _mark_slot_covered(meeting_id, "owners", "All extracted commitments have named owners")

    if MOCK_MODE:
        return _mock_agenda_update(meeting_id)

    # LLM matching for remaining slots
    non_owner_slots = [s for s in pending_slots if s["slot_id"] != "owners"]
    if not non_owner_slots:
        return

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": AGENDA_SLOT_MATCHING_PROMPT.format(
                        meeting_type=meeting_type,
                        slots_json=json.dumps([dict(s) for s in non_owner_slots]),
                        transcript_chunk=chunk
                    )
                },
                {"role": "user", "content": "Analyze this chunk."}
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"}
        )

        raw = response.choices[0].message.content
        results = _parse_json_list(raw, preferred_key="results")

        for r in results:
            if r.get("status") == "covered":
                _mark_slot_covered(meeting_id, r["slot_id"], r.get("evidence_quote", ""))
    except Exception as e:
        print(f"Agenda matching failed (non-fatal): {e}")
        pass  # Agenda matching is best-effort, never crash the main pipeline

def _mark_slot_covered(meeting_id: str, slot_id: str, evidence: str):
    conn = get_db()
    conn.execute("""
        UPDATE agenda_state
        SET status='covered', evidence_quote=?, covered_at=?
        WHERE meeting_id=? AND slot_id=?
    """, (evidence, datetime.utcnow().isoformat(), meeting_id, slot_id))
    conn.commit()
    conn.close()

def get_agenda_status(meeting_id: str) -> dict:
    """Returns current state of all agenda slots for a meeting."""
    conn = get_db()
    rows = conn.execute("""
        SELECT slot_id, label, required, status, evidence_quote, covered_at
        FROM agenda_state WHERE meeting_id=?
    """, (meeting_id,)).fetchall()
    conn.close()

    slots = [dict(r) for r in rows]
    missed_required = [s for s in slots if s["required"] and s["status"] == "pending"]

    return {
        "slots": slots,
        "all_covered": len(missed_required) == 0,
        "missed_required": missed_required,
        "alert_message": _build_alert(missed_required) if missed_required else None
    }

def _build_alert(missed: list) -> str:
    labels = [s["label"] for s in missed]
    return f"Before you close — {len(missed)} required item(s) not discussed: {', '.join(labels)}"

def check_wrapup_cue(chunk: str) -> bool:
    """Detect if the meeting is wrapping up."""
    cues = [
        "okay, anything else", "let's wrap", "wrap up", "that's all",
        "good meeting", "talk later", "thanks everyone", "we'll close",
        "any final", "last thing", "before we go"
    ]
    chunk_lower = chunk.lower()
    return any(cue in chunk_lower for cue in cues)

def _mock_agenda_update(meeting_id: str):
    _mark_slot_covered(meeting_id, "blockers", "Mock: blockers discussed")
