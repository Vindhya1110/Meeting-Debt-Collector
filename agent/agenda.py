import os
import json
import glob
from datetime import datetime
from llm import call, parse_json_list
from prompts import AGENDA_MATCH_PROMPT
from models import get_db
from notion_reporter import log_agenda_slot

MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

TEMPLATES = {}
WRAPUP_CUES = [
    "okay anything else", "let's wrap", "wrap up", "that's all",
    "thanks everyone", "any final", "last thing", "before we go", "we'll close"
]

def load_templates():
    base = os.path.join(os.path.dirname(__file__), "templates")
    for path in glob.glob(f"{base}/*.json"):
        with open(path) as f:
            t = json.load(f)
            TEMPLATES[t["type"]] = t["slots"]

def init_for_meeting(meeting_id: str, meeting_type: str):
    slots = TEMPLATES.get(meeting_type, TEMPLATES.get("club_meeting", []))
    conn = get_db()
    for s in slots:
        conn.execute(
            "INSERT OR IGNORE INTO agenda_state "
            "(meeting_id,slot_id,label,required,status) VALUES (?,?,?,?,'pending')",
            (meeting_id, s["id"], s["label"], 1 if s.get("required") else 0)
        )
    conn.commit()
    conn.close()

def process_chunk(meeting_id: str, meeting_type: str,
                   chunk: str, commitments: list) -> dict:
    conn = get_db()
    pending = conn.execute(
        "SELECT * FROM agenda_state WHERE meeting_id=? AND status='pending'",
        (meeting_id,)
    ).fetchall()
    conn.close()

    if not pending:
        return get_status(meeting_id)

    # Special: "owners" slot computed from commitments, not LLM-matched
    for s in pending:
        if s["slot_id"] == "owners":
            ownerless = [c for c in commitments if c.get("owner_type") == "ownerless"]
            if not ownerless and commitments:
                _cover(meeting_id, "owners", "All commitments have named owners")

    if not MOCK:
        non_owner = [dict(s) for s in pending if s["slot_id"] != "owners"]
        if non_owner:
            try:
                raw = call(
                    system=AGENDA_MATCH_PROMPT.format(
                        meeting_type=meeting_type,
                        slots_json=json.dumps(non_owner),
                        chunk=chunk
                    ),
                    user="Analyze this chunk.",
                    temperature=0.1, max_tokens=600, expect_json=True,
                    provider="groq"
                )
                results = parse_json_list(raw, preferred_key="results")
                for res in results:
                    if res.get("status") == "covered":
                        _cover(meeting_id, res["slot_id"], res.get("evidence_quote", ""))
            except Exception as e:
                print(f"[Agenda] match failed (non-fatal): {e}")

    is_wrap = any(cue in chunk.lower() for cue in WRAPUP_CUES)
    status = get_status(meeting_id)
    if is_wrap and status["missed_required"]:
        from nudger import send_wrapup_alert
        send_wrapup_alert(meeting_id, status["missed_required"])

    return status

def get_status(meeting_id: str) -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM agenda_state WHERE meeting_id=?", (meeting_id,)
    ).fetchall()
    conn.close()
    slots = [dict(r) for r in rows]
    missed = [s for s in slots if s["required"] and s["status"] == "pending"]
    return {"slots": slots, "missed_required": missed,
            "all_covered": len(missed) == 0}

def _cover(meeting_id, slot_id, evidence):
    conn = get_db()
    conn.execute(
        "UPDATE agenda_state SET status='covered',evidence_quote=?,covered_at=? "
        "WHERE meeting_id=? AND slot_id=?",
        (evidence, datetime.utcnow().isoformat(), meeting_id, slot_id)
    )
    conn.commit()
    conn.close()

    log_agenda_slot(meeting_id, {
        "label": slot_id, "required": True,
        "status": "covered", "evidence_quote": evidence
    })
