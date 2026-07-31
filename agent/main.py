import os
import uuid
import json
import asyncio
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db, get_agent_now, advance_clock, log_event
from extractor import extract
from resolver import resolve
from similarity import classify, get_embedding, cosine_similarity
from agenda import load_templates, init_for_meeting, process_chunk, get_status
from nudger import (send_ownerless_alert, send_beneficiary_done,
                     send_overcommit_warning, send_recommit_warning)
from scheduler import start as start_scheduler, cascade
from notion_reporter import (
    setup_notion_workspace, create_meeting_page, update_meeting_page,
    create_commitment_page, update_commitment_status, upsert_person_page,
    create_pattern_report_page
)

app = FastAPI(title="Meeting Debt Collector Agent")

app.add_middleware(CORSMiddleware,
    allow_origins=["*", "https://meet.google.com", "https://zoom.us",
                   "https://teams.microsoft.com", "chrome-extension://*"],
    allow_methods=["*"], allow_headers=["*"])

# ── Request models ─────────────────────────────────────────────────────────────

class MeetingStart(BaseModel):
    title: str
    type: str = "club_meeting"
    platform: str = "unknown"
    owner: str = ""
    attendees: List[dict] = []
    pre_brief: str = ""        # pre-meeting context / agenda items entered by user
    transcript: Optional[str] = ""  # optional: process a full transcript in one shot

class ChunkReq(BaseModel):
    chunk: str
    chunk_index: int = 0

class ActionReq(BaseModel):
    action: str
    new_deadline: Optional[str] = None
    new_owner: Optional[str] = None

class PreBriefReq(BaseModel):
    attendees: List[str]
    context_notes: str = ""

# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    load_templates()
    setup_notion_workspace()   # creates Notion DBs if not exist
    start_scheduler()
    print("[Agent] Running. Extension or dashboard can now connect.")

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/meetings/start")
async def start_meeting(req: MeetingStart):
    """
    Called by the extension when live capture starts, or by the dashboard
    when creating a meeting manually. Creates the meeting in SQLite + Notion.
    """
    mid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    pre_brief_text = req.pre_brief
    if req.attendees and not pre_brief_text:
        pre_brief_text = _gen_pre_brief(
            [a.get("name", a) if isinstance(a, dict) else a for a in req.attendees]
        )

    conn = get_db()
    conn.execute(
        "INSERT INTO meetings "
        "(id,title,type,platform,date,owner,attendees,pre_brief,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (mid, req.title, req.type, req.platform, now, req.owner,
         json.dumps(req.attendees), pre_brief_text, now)
    )
    conn.commit()
    conn.close()

    init_for_meeting(mid, req.type)

    notion_page = create_meeting_page({
        "id": mid, "title": req.title, "type": req.type,
        "platform": req.platform, "date": now, "owner": req.owner
    })
    if notion_page:
        conn = get_db()
        conn.execute("UPDATE meetings SET notion_page_id=? WHERE id=?", (notion_page, mid))
        conn.commit()
        conn.close()

        if pre_brief_text:
            from notion_reporter import _post
            _post(f"blocks/{notion_page}/children", {"children": [
                {"object": "block", "type": "callout",
                 "callout": {"rich_text": [{"text": {"content":
                     f"Pre-meeting context:\n{pre_brief_text}"
                 }}], "icon": {"emoji": "📋"}}}
            ]})

    result = {"meeting_id": mid, "notion_page": notion_page, "pre_brief": pre_brief_text}

    # Optional one-shot path: dashboard can pass a full transcript directly
    # instead of streaming it in via /chunk.
    if req.transcript:
        chunk_result = await _ingest(mid, req.transcript)
        result["commitments"] = chunk_result["commitments"]

    return result

@app.post("/meetings/{mid}/chunk")
async def ingest_chunk(mid: str, req: ChunkReq):
    """Called every ~30s by the extension with the latest caption chunk."""
    return await _ingest(mid, req.chunk)

_meeting_locks = defaultdict(asyncio.Lock)

async def _ingest(mid: str, chunk: str) -> dict:
    # Guard against overlapping chunks for the same meeting (e.g. the extension
    # firing a new chunk before the previous one finished processing) racing
    # each other in the similarity engine's read-then-write duplicate check.
    async with _meeting_locks[mid]:
        return await _ingest_locked(mid, chunk)

async def _ingest_locked(mid: str, chunk: str) -> dict:
    conn = get_db()
    m = conn.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m:
        raise HTTPException(404, "Meeting not found")
    m = dict(m)

    conn = get_db()
    conn.execute("UPDATE meetings SET transcript=transcript||? WHERE id=?", ("\n" + chunk, mid))
    conn.commit()
    conn.close()

    attendees = json.loads(m["attendees"])

    raw = extract(chunk, attendees, mid)
    resolved = resolve(raw)
    _resolve_dependencies(resolved)

    saved = []
    for c in resolved:
        saved.append(_save_commitment(c, m["owner"], m.get("notion_page_id", ""), m["title"]))

    all_c = _all_commitments(mid)
    agenda = process_chunk(mid, m["type"], chunk, all_c)

    update_meeting_page(m.get("notion_page_id", ""), {"commitments_count": len(all_c)})

    return {
        "meeting_id": mid,
        "commitments_this_chunk": len([s for s in saved if s.get("action_taken") == "created"]),
        "commitments": saved,
        "total_commitments": len(all_c),
        "agenda": agenda
    }

@app.post("/meetings/{mid}/end")
async def end_meeting(mid: str):
    """
    Called when live capture stops (extension) or when finalizing manually
    (dashboard). Generates MoM, posts full report to Notion, triggers pattern report.
    """
    conn = get_db()
    m = conn.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m:
        raise HTTPException(404, "Meeting not found")
    m = dict(m)

    commitments = _all_commitments(mid)
    agenda = get_status(mid)

    mom = _gen_mom(m, commitments, agenda)

    conn = get_db()
    conn.execute("UPDATE meetings SET mom=?,status='finalized' WHERE id=?", (mom, mid))
    conn.commit()
    conn.close()

    notion_page = m.get("notion_page_id", "")
    update_meeting_page(notion_page, {
        "status": "finalized", "mom": mom, "agenda": agenda,
        "commitments_count": len(commitments),
    })

    for s in agenda["slots"]:
        from notion_reporter import log_agenda_slot
        log_agenda_slot(mid, s)

    report = _gen_pattern_report()
    create_pattern_report_page(report["summary"], report["stats"], report["debt"])

    return {
        "meeting_id": mid,
        "commitments": len(commitments),
        "mom": mom,
        "mom_generated": bool(mom),
        "missed_agenda": len(agenda["missed_required"]),
        "notion_page": notion_page
    }

@app.post("/meetings/{mid}/pre-brief")
async def get_pre_brief(mid: str, req: PreBriefReq):
    """Generate (or regenerate) a 'since we last spoke' briefing on demand."""
    brief = _gen_pre_brief(req.attendees, req.context_notes)
    return {"brief": brief}

@app.get("/meetings")
async def list_meetings():
    conn = get_db()
    rows = conn.execute("SELECT * FROM meetings ORDER BY created_at DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["attendees"] = json.loads(d["attendees"])
        except (TypeError, json.JSONDecodeError):
            d["attendees"] = []
        out.append(d)
    return {"meetings": out}

@app.post("/commitments/{cid}/action")
async def commitment_action(cid: str, req: ActionReq):
    """Human action — called from Slack/WhatsApp reply, the dashboard, or a direct POST."""
    conn = get_db()
    c = conn.execute("SELECT * FROM commitments WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not c:
        raise HTTPException(404, "Commitment not found")
    c = dict(c)
    now = datetime.utcnow().isoformat()

    if req.action == "done":
        _update_c(cid, {"status": "done", "updated_at": now})
        send_beneficiary_done(c)
        _bump_stat(c["owner"], "on_time")
        log_event(cid, "done")

    elif req.action == "need_time":
        if not req.new_deadline:
            raise HTTPException(400, "new_deadline required")
        # Reset to 'open' (not a terminal 'renegotiated' status) so the watch
        # loop keeps nudging/escalating/missing against the NEW deadline — the
        # renegotiation itself is recorded in commitment_history below.
        _update_c(cid, {"status": "open", "deadline": req.new_deadline, "updated_at": now})
        try:
            old_h = datetime.fromisoformat(c["deadline"])
            new_h = datetime.fromisoformat(req.new_deadline)
            dh = (new_h - old_h).total_seconds() / 3600
            if dh > 0:
                cascade(cid, dh, c.get("normalized_task", "?"))
        except (ValueError, TypeError):
            pass
        log_event(cid, "renegotiated", req.new_deadline)
        _bump_stat(c["owner"], "renegotiated")

    elif req.action == "assign_owner":
        if not req.new_owner:
            raise HTTPException(400, "new_owner required")
        _update_c(cid, {"owner": req.new_owner, "owner_type": "person", "updated_at": now})
        log_event(cid, "assigned", req.new_owner)

    elif req.action == "reassign":
        if not req.new_owner:
            raise HTTPException(400, "new_owner required")
        _update_c(cid, {"owner": req.new_owner, "status": "open", "updated_at": now})
        log_event(cid, "reassigned", req.new_owner)

    elif req.action in ("approve", "reject"):
        new_s = "open" if req.action == "approve" else "missed"
        _update_c(cid, {"status": new_s, "updated_at": now})
        log_event(cid, req.action)

    else:
        raise HTTPException(400, f"Unknown action: {req.action}")

    conn = get_db()
    updated = conn.execute("SELECT * FROM commitments WHERE id=?", (cid,)).fetchone()
    conn.close()
    update_commitment_status(
        dict(updated).get("notion_page_id", ""),
        dict(updated)["status"], detail=f"Action: {req.action}"
    )
    return {"ok": True}

@app.post("/simulate")
async def simulate(advance_hours: float = 24.0):
    """★ DEMO ENDPOINT — advance agent clock and run watch loop immediately."""
    new_now = advance_clock(advance_hours)
    from scheduler import tick
    tick()
    return {"advanced_hours": advance_hours, "agent_now": new_now}

@app.get("/simulate/reset")
async def reset_clock():
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=?", (now,))
    conn.commit()
    conn.close()
    return {"reset_to": now}

@app.get("/health")
async def health():
    return {"status": "ok", "agent_now": get_agent_now().isoformat(),
            "mock": os.getenv("MOCK_MODE", "false")}

@app.get("/commitments")
async def list_commitments(status: str = None, owner: str = None):
    conn = get_db()
    q = ("SELECT c.*,m.title as meeting_title FROM commitments c "
         "JOIN meetings m ON c.meeting_id=m.id WHERE 1=1")
    p = []
    if status:
        q += " AND c.status=?"
        p.append(status)
    if owner:
        q += " AND c.owner=?"
        p.append(owner)
    rows = conn.execute(q + " ORDER BY c.deadline ASC", p).fetchall()
    conn.close()
    return {"commitments": [dict(r) for r in rows]}

# ── Additive read endpoints (support the standalone dashboard) ────────────────

@app.get("/agenda/{mid}")
async def agenda_status(mid: str):
    status = get_status(mid)
    status["alert_message"] = (
        f"Before you close — {len(status['missed_required'])} required item(s) "
        f"not discussed: {', '.join(s['label'] for s in status['missed_required'])}"
    ) if status["missed_required"] else None
    return status

@app.get("/report/people")
async def people_report():
    report = _gen_pattern_report(write_to_notion=False)
    return {
        "stats": report["stats"],
        "summary": report["summary"],
        "flagged": [s for s in report["stats"] if s.get("at_risk")]
    }

@app.get("/report/meetings")
async def meetings_report():
    return {"meetings": _gen_pattern_report(write_to_notion=False)["debt"]}

# ── Helpers ────────────────────────────────────────────────────────────────────

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
        {"id": c.get("id"), "owner": c.get("owner", ""), "normalized_task": c.get("normalized_task", "")}
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

def _save_commitment(c: dict, meeting_owner: str, meeting_notion_id: str, meeting_title: str) -> dict:
    if c.get("owner_type") == "ownerless":
        send_ownerless_alert(c, meeting_owner)

    if c.get("owner_type") == "person":
        result = classify(c)
        action = result["action"]

        if action == "renegotiate":
            conn = get_db()
            target_before = conn.execute(
                "SELECT deadline FROM commitments WHERE id=?", (result["target_id"],)
            ).fetchone()
            conn.close()

            # Reset to 'open' (see the identical comment in commitment_action) so
            # the watch loop keeps tracking the new deadline instead of the item
            # silently falling out of nudge/escalate/miss monitoring forever.
            _update_c(result["target_id"], {
                "deadline": c.get("deadline", ""),
                "status": "open",
                "updated_at": datetime.utcnow().isoformat()
            })
            log_event(result["target_id"], "renegotiated",
                      f"Detected in transcript: \"{c.get('commitment_text', '')}\"")

            if target_before and target_before["deadline"] and c.get("deadline"):
                try:
                    old_dl = datetime.fromisoformat(target_before["deadline"])
                    new_dl = datetime.fromisoformat(c["deadline"])
                    delay_h = (new_dl - old_dl).total_seconds() / 3600
                    if delay_h > 0:
                        cascade(result["target_id"], delay_h, c.get("normalized_task", "?"))
                except (ValueError, TypeError):
                    pass

            return {**c, "action_taken": "renegotiated_existing"}

        if action == "merge":
            log_event(result["target_id"], "merged")
            return {**c, "action_taken": "merged_with_existing"}

        if action == "recommit":
            c["warning"] = result.get("warning", "")
            send_recommit_warning(c, c["warning"])

    # Overcommitment check
    conn = get_db()
    conn.execute("""
        INSERT INTO person_stats (person, committed) VALUES (?, 1)
        ON CONFLICT(person) DO UPDATE SET committed = committed + 1
    """, (c.get("owner", "Unknown"),))
    conn.commit()
    stat = conn.execute("SELECT * FROM person_stats WHERE person=?", (c.get("owner", ""),)).fetchone()
    open_n = conn.execute("""SELECT COUNT(*) as n FROM commitments
        WHERE owner=? AND status IN ('open','nudged','escalated')""",
        (c.get("owner", ""),)).fetchone()["n"]
    conn.close()
    if stat and stat["avg_completion_per_week"] and open_n > stat["avg_completion_per_week"] * 1.5:
        send_overcommit_warning(c["owner"], open_n, stat["avg_completion_per_week"])

    notion_page = create_commitment_page(c, meeting_title)
    if notion_page:
        c["notion_page_id"] = notion_page

    conn = get_db()
    conn.execute("""
        INSERT OR IGNORE INTO commitments
        (id,meeting_id,owner,beneficiary,commitment_text,normalized_task,
         explicit_deadline,deadline,original_deadline,deadline_clue,
         status,owner_type,item_type,assigned_by,confidence,
         depends_on,nudge_count,timestamp_sec,warning,notion_page_id,
         created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        c["id"], c["meeting_id"], c.get("owner", "?"),
        c.get("beneficiary", "") or "", c.get("commitment_text", ""),
        c.get("normalized_task", ""), c.get("explicit_deadline", "") or "",
        c.get("deadline", "") or "", c.get("original_deadline", "") or "",
        c.get("deadline_clue", "") or "", c.get("status", "open"),
        c.get("owner_type", "person"), c.get("item_type", "self_commitment"),
        c.get("assigned_by", "") or "", c.get("confidence", 0.9),
        c.get("depends_on", "") or "", 0, c.get("timestamp_sec", 0),
        c.get("warning", "") or "", c.get("notion_page_id", ""),
        c["created_at"], c["updated_at"]
    ))
    conn.commit()
    conn.close()
    log_event(c["id"], "extracted")
    return {**c, "action_taken": "created"}

def _gen_mom(m: dict, commitments: list, agenda: dict) -> str:
    from llm import call
    from prompts import MOM_PROMPT
    try:
        return call(
            system="You write professional meeting minutes.",
            user=MOM_PROMPT.format(
                title=m["title"], date=m["date"],
                attendees=m.get("attendees", "[]"),
                transcript=m.get("transcript", "")[:3000],
                commitments_json=json.dumps(commitments[:20]),
                agenda_json=json.dumps(agenda.get("slots", []))
            ),
            temperature=0.3, max_tokens=1500, expect_json=False
        )
    except Exception as e:
        print(f"[MoM] generation failed: {e}")
        return ""

def _gen_pre_brief(attendees: list, context: str = "") -> str:
    from llm import call
    from prompts import CROSS_MEETING_BRIEF_PROMPT

    if not attendees:
        return ""

    conn = get_db()
    placeholders = ",".join("?" * len(attendees))
    open_items = conn.execute(f"""
        SELECT c.*, m.title as meeting_title
        FROM commitments c JOIN meetings m ON c.meeting_id=m.id
        WHERE c.owner IN ({placeholders}) AND c.status IN ('open','nudged','escalated','missed')
        ORDER BY c.deadline ASC LIMIT 20
    """, attendees).fetchall()

    recommits = conn.execute(f"""
        SELECT owner, normalized_task, COUNT(*) as n
        FROM commitments WHERE owner IN ({placeholders})
        GROUP BY owner, normalized_task HAVING n > 1
    """, attendees).fetchall()
    conn.close()

    flags = [f"{r['owner']} committed to '{r['normalized_task']}' {r['n']} times"
             for r in recommits]
    if context:
        flags.append(f"Pre-meeting context: {context}")

    if not open_items and not flags:
        return "Nothing outstanding from prior meetings for this group."

    try:
        return call(
            system="You generate concise pre-meeting briefings.",
            user=CROSS_MEETING_BRIEF_PROMPT.format(
                attendees=", ".join(attendees),
                open_items_json=json.dumps([dict(i) for i in open_items]),
                flags_json=json.dumps(flags)
            ),
            temperature=0.3, max_tokens=400, expect_json=False
        )
    except Exception as e:
        print(f"[PreBrief] generation failed: {e}")
        return ""

def _gen_pattern_report(write_to_notion: bool = True) -> dict:
    from llm import call
    from prompts import PATTERN_REPORT_PROMPT

    conn = get_db()
    stats = conn.execute("SELECT * FROM person_stats ORDER BY missed DESC").fetchall()
    debt = conn.execute("""
        SELECT m.id,m.title,m.date,m.type,
               COUNT(c.id) as total_commitments,
               SUM(CASE WHEN c.status='done' THEN 1 ELSE 0 END) as completed,
               SUM(CASE WHEN c.status='missed' THEN 1 ELSE 0 END) as missed
        FROM meetings m LEFT JOIN commitments c ON c.meeting_id=m.id
        GROUP BY m.id ORDER BY m.date DESC
    """).fetchall()
    conn.close()

    stats_list = []
    for s in stats:
        s = dict(s)
        total = s.get("committed", 0) or 1
        s["follow_through"] = round(s.get("on_time", 0) / total, 2)
        s["follow_through_rate"] = s["follow_through"]
        s["at_risk"] = s["follow_through"] < 0.5 and s.get("committed", 0) >= 3
        stats_list.append(s)
        if write_to_notion:
            upsert_person_page(s)

    debt_list = []
    for d in debt:
        d = dict(d)
        t = d.get("total_commitments", 0) or 1
        d["rate"] = round((d.get("completed") or 0) / t, 2)
        d["follow_through_rate"] = d["rate"]
        d["debt_score"] = round((d.get("missed") or 0) / t, 2)
        d["suggest_async"] = d["rate"] < 0.3 and d.get("total_commitments", 0) >= 3
        debt_list.append(d)

    try:
        summary = call(
            system="You write coaching summaries for team leads.",
            user=PATTERN_REPORT_PROMPT.format(stats_json=json.dumps(stats_list)),
            temperature=0.4, max_tokens=300, expect_json=False
        )
    except Exception as e:
        print(f"[PatternReport] summary generation failed: {e}")
        summary = "Pattern report generated."

    return {"summary": summary, "stats": stats_list, "debt": debt_list}

def _all_commitments(meeting_id: str) -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM commitments WHERE meeting_id=?", (meeting_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _update_c(cid: str, fields: dict):
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE commitments SET {sets} WHERE id=?", list(fields.values()) + [cid])
    conn.commit()
    conn.close()

def _bump_stat(person: str, field: str):
    conn = get_db()
    conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
    conn.commit()
    conn.close()

# ── Static frontend (optional manual dashboard) ────────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
