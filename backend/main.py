import os
import uuid
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db, get_agent_now, advance_agent_clock
from extractor import extract_commitments
from resolver import resolve_deadlines
from similarity import classify_against_open, get_embedding, cosine_similarity
from agenda import (
    load_templates, init_agenda_for_meeting,
    process_chunk_for_agenda, get_agenda_status, check_wrapup_cue
)
from notion_mirror import mirror_commitment
from nudger import send_ownerless_alert, send_beneficiary_notification
from scheduler import start_scheduler

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

app = FastAPI(title="Meeting Debt Collector")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def startup():
    init_db()
    load_templates()
    start_scheduler()

# --- REQUEST MODELS ---------------------------------------------------------

class Attendee(BaseModel):
    name: str
    email: Optional[str] = ""
    slack_handle: Optional[str] = ""

class MeetingCreate(BaseModel):
    title: str
    type: str                      # sprint_review | event_planning | project_kickoff | club_meeting
    owner: str                     # meeting chair name
    attendees: List[Attendee]
    transcript: Optional[str] = ""

class ChunkRequest(BaseModel):
    chunk: str                     # ~30s transcript text
    chunk_index: int

class CommitmentAction(BaseModel):
    action: str                    # done | need_time | assign_owner | approve | reject | reassign
    new_deadline: Optional[str] = None
    new_owner: Optional[str] = None

class CalendarConfirm(BaseModel):
    draft: dict
    attendee_emails: List[str]

# --- ROUTES ------------------------------------------------------------------

@app.post("/meetings")
async def create_meeting(data: MeetingCreate):
    """Create a meeting. If transcript provided, process immediately."""
    meeting_id = str(uuid.uuid4())
    attendees = [a.model_dump() for a in data.attendees]
    conn = get_db()
    conn.execute("""
        INSERT INTO meetings (id, title, type, date, owner, attendees, transcript, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        meeting_id, data.title, data.type,
        datetime.utcnow().isoformat(), data.owner,
        json.dumps(attendees), data.transcript,
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

    # Initialize agenda template
    init_agenda_for_meeting(meeting_id, data.type)

    result = {"meeting_id": meeting_id, "status": "created"}

    # If full transcript provided (non-chunked path), process now
    if data.transcript:
        processed = await _process_full_transcript(meeting_id, data.type, data.transcript, attendees, data.owner)
        result["commitments"] = processed

    return result

@app.post("/meetings/{meeting_id}/chunk")
async def ingest_chunk(meeting_id: str, data: ChunkRequest):
    """
    Live chunked ingestion. Called every ~30s during a meeting.
    Extracts commitments from this chunk and updates agenda state.
    """
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    conn.close()

    if not meeting:
        raise HTTPException(404, "Meeting not found")

    meeting = dict(meeting)
    attendees = json.loads(meeting["attendees"])

    # Extract from this chunk
    raw_commitments = extract_commitments(data.chunk, attendees, meeting_id)
    resolved = resolve_deadlines(raw_commitments)
    _resolve_dependencies(resolved)

    saved = []
    for c in resolved:
        result = _save_commitment(c, meeting["owner"])
        saved.append(result)

    # Update agenda coverage
    all_commitments = _get_meeting_commitments(meeting_id)
    process_chunk_for_agenda(meeting_id, meeting["type"], data.chunk, all_commitments)

    # Check for wrap-up cue
    wrap_up_detected = check_wrapup_cue(data.chunk)
    agenda = get_agenda_status(meeting_id)

    return {
        "commitments_extracted": len(saved),
        "commitments": saved,
        "agenda": agenda,
        "wrap_up_detected": wrap_up_detected,
        "alert": agenda.get("alert_message") if wrap_up_detected else None
    }

@app.post("/meetings/{meeting_id}/finalize")
async def finalize_meeting(meeting_id: str):
    """Generate MoM and finalize meeting status."""
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    conn.close()

    if not meeting:
        raise HTTPException(404, "Meeting not found")

    meeting = dict(meeting)
    commitments = _get_meeting_commitments(meeting_id)

    from prompts import MOM_GENERATION_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": MOM_GENERATION_PROMPT.format(
            meeting_title=meeting["title"],
            meeting_date=meeting["date"],
            attendees=meeting["attendees"],
            transcript=meeting["transcript"],
            commitments_json=json.dumps(commitments)
        )}],
        temperature=0.3,
        max_tokens=1000
    )
    mom = response.choices[0].message.content

    conn = get_db()
    conn.execute("UPDATE meetings SET status='finalized' WHERE id=?", (meeting_id,))
    conn.commit()
    conn.close()

    return {"mom": mom, "commitments": commitments}

@app.get("/meetings/{meeting_id}/pre-brief")
async def pre_meeting_brief(meeting_id: str):
    """
    Cross-Meeting Context Injection.
    Generates 'since we last spoke' briefing for the meeting chair.
    """
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    conn.close()

    if not meeting:
        raise HTTPException(404, "Meeting not found")

    meeting = dict(meeting)
    attendees_list = [a["name"] for a in json.loads(meeting["attendees"])]

    if not attendees_list:
        return {"brief": "No attendees to brief.", "open_count": 0, "flags": []}

    placeholders = ",".join(["?"] * len(attendees_list))

    conn = get_db()
    open_items = conn.execute(f"""
        SELECT c.*, m.title as meeting_title, m.date as meeting_date
        FROM commitments c
        JOIN meetings m ON c.meeting_id = m.id
        WHERE c.owner IN ({placeholders})
        AND c.status IN ('open', 'nudged', 'escalated', 'missed')
        AND c.meeting_id != ?
        ORDER BY c.deadline ASC
    """, attendees_list + [meeting_id]).fetchall()

    recommits = conn.execute(f"""
        SELECT owner, normalized_task, COUNT(*) as count
        FROM commitments
        WHERE owner IN ({placeholders})
        GROUP BY owner, normalized_task
        HAVING count > 1
    """, attendees_list).fetchall()
    conn.close()

    flags = [
        f"{r['owner']} has committed to '{r['normalized_task']}' {r['count']} times"
        for r in recommits
    ]

    if not open_items and not flags:
        return {"brief": "Nothing outstanding from prior meetings for this group.", "open_count": 0, "flags": []}

    from prompts import CROSS_MEETING_SUMMARY_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": CROSS_MEETING_SUMMARY_PROMPT.format(
            attendees=", ".join(attendees_list),
            open_commitments_json=json.dumps([dict(i) for i in open_items]),
            flags_json=json.dumps(flags)
        )}],
        temperature=0.3,
        max_tokens=400
    )

    return {
        "brief": response.choices[0].message.content,
        "open_count": len(open_items),
        "flags": flags
    }

@app.get("/commitments")
async def list_commitments(
    status: Optional[str] = None,
    owner: Optional[str] = None,
    meeting_id: Optional[str] = None
):
    """Dashboard feed with optional filters."""
    conn = get_db()
    query = """
        SELECT c.*, m.title as meeting_title
        FROM commitments c
        JOIN meetings m ON c.meeting_id = m.id
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND c.status=?"
        params.append(status)
    if owner:
        query += " AND c.owner=?"
        params.append(owner)
    if meeting_id:
        query += " AND c.meeting_id=?"
        params.append(meeting_id)

    query += " ORDER BY c.deadline ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return {"commitments": [dict(r) for r in rows]}

@app.get("/meetings")
async def list_meetings():
    """List all meetings, most recent first."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM meetings ORDER BY created_at DESC").fetchall()
    conn.close()
    meetings = []
    for r in rows:
        m = dict(r)
        m["attendees"] = json.loads(m["attendees"])
        meetings.append(m)
    return {"meetings": meetings}

@app.post("/commitments/{commitment_id}/action")
async def commitment_action(commitment_id: str, data: CommitmentAction):
    """Human actions on a commitment from the dashboard."""
    conn = get_db()
    item = conn.execute("SELECT * FROM commitments WHERE id=?", (commitment_id,)).fetchone()
    conn.close()

    if not item:
        raise HTTPException(404, "Commitment not found")

    item = dict(item)
    now = datetime.utcnow().isoformat()

    if data.action == "done":
        _update_commitment(commitment_id, {"status": "done", "updated_at": now})
        send_beneficiary_notification(item)
        _update_person_stats_done(item["owner"])

    elif data.action == "need_time":
        if not data.new_deadline:
            raise HTTPException(400, "new_deadline required for need_time action")
        # Reset to 'open' (not a terminal 'renegotiated' status) so the watch
        # loop keeps nudging/escalating/missing against the NEW deadline —
        # the renegotiation itself is recorded in commitment_history below.
        _update_commitment(commitment_id, {
            "status": "open",
            "deadline": data.new_deadline,
            "updated_at": now
        })
        _update_person_stats(item["owner"], "renegotiated")
        from scheduler import _log_event
        _log_event(commitment_id, "renegotiated", f"Deadline moved from {item.get('deadline')} to {data.new_deadline}")
        # Cascade the delay
        if item.get("deadline"):
            try:
                old_dl = datetime.fromisoformat(item["deadline"])
                new_dl = datetime.fromisoformat(data.new_deadline)
                delay_hours = (new_dl - old_dl).total_seconds() / 3600
                if delay_hours > 0:
                    from scheduler import _check_cascade
                    _check_cascade(commitment_id, delay_hours)
            except ValueError:
                pass

    elif data.action == "assign_owner":
        if not data.new_owner:
            raise HTTPException(400, "new_owner required")
        _update_commitment(commitment_id, {
            "owner": data.new_owner,
            "owner_type": "person",
            "updated_at": now
        })

    elif data.action == "reassign":
        if not data.new_owner:
            raise HTTPException(400, "new_owner required for reassign")
        _update_commitment(commitment_id, {
            "owner": data.new_owner,
            "status": "open",
            "updated_at": now
        })

    elif data.action in ("approve", "reject"):
        # Confidence-gated review queue (U4)
        new_status = "open" if data.action == "approve" else "missed"
        _update_commitment(commitment_id, {"status": new_status, "updated_at": now})

    else:
        raise HTTPException(400, f"Unknown action: {data.action}")

    return {"status": "ok", "action": data.action}

@app.post("/calendar/confirm")
async def confirm_calendar_event(data: CalendarConfirm):
    """Human confirmed a follow-up meeting proposal. Create it now."""
    from calendar_agent import create_confirmed_event
    link = create_confirmed_event(data.draft, data.attendee_emails)
    if not link:
        return {"meet_link": "", "status": "calendar_not_connected"}
    return {"meet_link": link, "status": "created"}

@app.post("/simulate")
async def simulate_time(advance_hours: float = 24):
    """
    THE DEMO ENDPOINT.
    Advances the agent's clock without waiting real time.
    Runs the watch loop immediately after advancing.
    """
    new_now = advance_agent_clock(advance_hours)
    from scheduler import run_watch_loop
    run_watch_loop()
    return {
        "advanced_by_hours": advance_hours,
        "agent_now": new_now,
        "message": f"Clock advanced by {advance_hours}h. Watch loop ran."
    }

@app.get("/simulate/reset")
async def reset_clock():
    """Reset agent clock to real current time."""
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=?", (now,))
    conn.commit()
    conn.close()
    return {"reset_to": now}

@app.get("/agenda/{meeting_id}")
async def agenda_status(meeting_id: str):
    return get_agenda_status(meeting_id)

@app.get("/report/people")
async def people_report():
    """Pattern detection report — private, for team lead only."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM person_stats ORDER BY missed DESC").fetchall()
    conn.close()

    stats = [dict(r) for r in rows]

    for s in stats:
        total = s["committed"] or 1
        s["follow_through_rate"] = round(s["on_time"] / total, 2)
        s["at_risk"] = s["follow_through_rate"] < 0.5 and s["committed"] >= 3

    from prompts import PATTERN_REPORT_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": PATTERN_REPORT_PROMPT.format(
            stats_json=json.dumps(stats)
        )}],
        temperature=0.4,
        max_tokens=200
    )

    return {
        "stats": stats,
        "summary": response.choices[0].message.content,
        "flagged": [s for s in stats if s["at_risk"]]
    }

@app.get("/report/meetings")
async def meetings_report():
    """Meeting-level debt score (U9)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            m.id, m.title, m.date, m.type,
            COUNT(c.id) as total_commitments,
            SUM(CASE WHEN c.status='done' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN c.status='missed' THEN 1 ELSE 0 END) as missed
        FROM meetings m
        LEFT JOIN commitments c ON c.meeting_id = m.id
        GROUP BY m.id
        ORDER BY m.date DESC
    """).fetchall()
    conn.close()

    meetings = []
    for r in rows:
        r = dict(r)
        total = r["total_commitments"] or 1
        r["follow_through_rate"] = round((r["completed"] or 0) / total, 2)
        r["debt_score"] = round((r["missed"] or 0) / total, 2)
        r["suggest_async"] = r["follow_through_rate"] < 0.3 and r["total_commitments"] >= 3
        meetings.append(r)

    return {"meetings": meetings}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": os.getenv("MOCK_MODE", "false"),
        "agent_now": get_agent_now().isoformat()
    }

# --- HELPERS ------------------------------------------------------------------

def _resolve_dependencies(commitments: list):
    """
    Match each commitment's free-text depends_on_hint (e.g. "once Alice finishes
    the API") to an actual commitment ID, so the scheduler's cascade-delay logic
    (WHERE depends_on = <id>) has something real to match against. Without this,
    depends_on would only ever hold an unresolvable text fragment.
    """
    hint_items = [c for c in commitments if c.get("depends_on_hint")]
    if not hint_items:
        return

    conn = get_db()
    db_open = conn.execute("""
        SELECT id, owner, normalized_task FROM commitments
        WHERE status IN ('open', 'nudged', 'escalated')
    """).fetchall()
    conn.close()

    candidates = [
        {"id": c["id"], "owner": c.get("owner", ""), "normalized_task": c.get("normalized_task", "")}
        for c in commitments
    ] + [dict(r) for r in db_open]

    for c in hint_items:
        hint = c["depends_on_hint"]
        hint_vec = get_embedding(hint)
        best_id, best_score = None, 0.0
        for cand in candidates:
            if cand["id"] == c.get("id"):
                continue
            score = cosine_similarity(hint_vec, get_embedding(cand["normalized_task"]))
            if cand["owner"] and cand["owner"].lower() in hint.lower():
                score += 0.25
            if score > best_score:
                best_score, best_id = score, cand["id"]
        if best_id and best_score >= 0.4:
            c["depends_on"] = best_id

def _save_commitment(commitment: dict, meeting_owner: str) -> dict:
    """
    Save a commitment to SQLite, handling similarity classification first.
    Returns the saved/updated commitment with its classification result.
    """
    # Confidence gate — route low-confidence to review queue
    if commitment.get("confidence", 1.0) < 0.8:
        commitment["status"] = "review"

    # Ownerless alert
    if commitment.get("owner_type") == "ownerless":
        send_ownerless_alert(commitment, meeting_owner)

    # Similarity classification (duplicate/renegotiate/recommit check)
    if commitment.get("owner_type") == "person":
        result = classify_against_open(commitment)
        commitment["similarity_action"] = result["action"]

        if result["action"] == "renegotiate":
            conn = get_db()
            target_before = conn.execute(
                "SELECT deadline FROM commitments WHERE id=?", (result["target_id"],)
            ).fetchone()
            conn.close()

            # Reset to 'open' (not a terminal 'renegotiated' status) so the watch
            # loop keeps nudging/escalating/missing against the NEW deadline —
            # the renegotiation itself is recorded in commitment_history below.
            _update_commitment(result["target_id"], {
                "deadline": commitment.get("deadline", ""),
                "status": "open",
                "updated_at": datetime.utcnow().isoformat()
            })
            _update_person_stats(commitment.get("owner", ""), "renegotiated")
            from scheduler import _log_event
            _log_event(result["target_id"], "renegotiated",
                       f"Detected in transcript: \"{commitment.get('commitment_text', '')}\"")

            # Propagate the delay to anything depending on this commitment (U3),
            # same as the dashboard's manual "need more time" action does.
            if target_before and target_before["deadline"] and commitment.get("deadline"):
                try:
                    old_dl = datetime.fromisoformat(target_before["deadline"])
                    new_dl = datetime.fromisoformat(commitment["deadline"])
                    delay_hours = (new_dl - old_dl).total_seconds() / 3600
                    if delay_hours > 0:
                        from scheduler import _check_cascade
                        _check_cascade(result["target_id"], delay_hours)
                except ValueError:
                    pass

            return {**commitment, "action_taken": "renegotiated_existing"}

        elif result["action"] == "merge":
            return {**commitment, "action_taken": "merged_with_existing"}

        elif result["action"] == "recommit":
            commitment["warning"] = result.get("warning", "")

    # Track total commitments per person
    conn = get_db()
    conn.execute("""
        INSERT INTO person_stats (person, committed) VALUES (?, 1)
        ON CONFLICT(person) DO UPDATE SET committed = committed + 1
    """, (commitment.get("owner", "Unknown"),))
    conn.commit()
    conn.close()

    # Insert new commitment
    conn = get_db()
    conn.execute("""
        INSERT INTO commitments
        (id, meeting_id, owner, beneficiary, commitment_text, normalized_task,
         explicit_deadline, deadline, original_deadline, deadline_clue,
         status, owner_type, item_type, assigned_by, confidence,
         depends_on, nudge_count, timestamp_sec, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        commitment["id"], commitment["meeting_id"],
        commitment.get("owner", "Unknown"),
        commitment.get("beneficiary") or "",
        commitment.get("commitment_text", ""),
        commitment.get("normalized_task", ""),
        commitment.get("explicit_deadline") or "",
        commitment.get("deadline") or "",
        commitment.get("original_deadline") or "",
        commitment.get("deadline_clue") or "",
        commitment.get("status", "open"),
        commitment.get("owner_type", "person"),
        commitment.get("item_type", "self_commitment"),
        commitment.get("assigned_by") or "",
        commitment.get("confidence", 0.9),
        commitment.get("depends_on") or "",
        0, commitment.get("timestamp_sec", 0),
        datetime.utcnow().isoformat(),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

    # Mirror to Notion (fire and forget)
    mirror_commitment(commitment)

    return {**commitment, "action_taken": "created"}

def _update_commitment(commitment_id: str, updates: dict):
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [commitment_id]
    conn.execute(f"UPDATE commitments SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()

def _get_meeting_commitments(meeting_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM commitments WHERE meeting_id=?", (meeting_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _update_person_stats_done(person: str):
    conn = get_db()
    conn.execute(
        "UPDATE person_stats SET on_time=on_time+1 WHERE person=?", (person,)
    )
    conn.commit()
    conn.close()

def _update_person_stats(person: str, event: str):
    field = {"missed": "missed", "renegotiated": "renegotiated", "on_time": "on_time"}.get(event)
    if not field or not person:
        return
    conn = get_db()
    conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
    conn.commit()
    conn.close()

async def _process_full_transcript(meeting_id: str, meeting_type: str, transcript: str, attendees: list, owner: str) -> list:
    """Process a full transcript in one shot (non-chunked path)."""
    raw = extract_commitments(transcript, attendees, meeting_id)
    resolved = resolve_deadlines(raw)
    _resolve_dependencies(resolved)
    saved = []
    for c in resolved:
        saved.append(_save_commitment(c, owner))
    process_chunk_for_agenda(meeting_id, meeting_type, transcript, resolved)
    return saved

# --- STATIC FRONTEND -----------------------------------------------------------
# Mounted last so it never shadows the API routes above.
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
