# MEETING DEBT COLLECTOR — COMPLETE BUILD SPEC
# Hand this file to Claude Code. Build top to bottom, section by section.
# Every file is production-ready. Do not skip any section.

---

## WHAT THIS SYSTEM IS

A background agent + Chrome extension combo that:
1. Joins any Google Meet / Zoom / Teams meeting as an extension
2. Captures live captions from the meeting DOM (zero audio processing)
3. Pre-loads context from before the meeting starts (pre-brief input)
4. Runs the full autonomous pipeline in the background
5. Writes ALL reports, commitments, MoM, pattern data to Notion in real time
6. Sends nudges via WhatsApp + Slack when deadlines approach
7. Never requires the user to open a dashboard

LLM: Featherless AI (OpenAI-compatible, free key provided)
Model: meta-llama/Meta-Llama-3.1-70B-Instruct (extraction, reasoning, reports)
Fast model: meta-llama/Llama-3.1-8B-Instruct (nudge messages, quick checks)

---

## COMPLETE FOLDER STRUCTURE

```
meeting-debt-collector/
│
├── README.md
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
│
├── agent/                          ← Python FastAPI backend
│   ├── main.py                     ← all HTTP routes
│   ├── models.py                   ← SQLite schema + DB helpers
│   ├── prompts.py                  ← every LLM prompt as a named constant
│   ├── llm.py                      ← Featherless API wrapper (single file)
│   ├── extractor.py                ← commitment extraction pipeline
│   ├── resolver.py                 ← deadline resolution
│   ├── similarity.py               ← duplicate/renegotiate/recommit engine
│   ├── nudger.py                   ← message gen + WhatsApp + Slack delivery
│   ├── scheduler.py                ← autonomous watch loop
│   ├── agenda.py                   ← live agenda coverage agent
│   ├── notion_reporter.py          ← ALL Notion writes (reports, commitments, MoM)
│   ├── calendar_agent.py           ← Google Calendar propose + create
│   ├── mock_mode.py                ← mock responses when MOCK_MODE=true
│   └── templates/
│       ├── sprint_review.json
│       ├── event_planning.json
│       ├── project_kickoff.json
│       └── club_meeting.json
│
└── extension/                      ← Chrome extension (works on Meet/Zoom/Teams)
    ├── manifest.json
    ├── background.js               ← service worker, state management
    ├── content_meet.js             ← injected into meet.google.com
    ├── content_zoom.js             ← injected into zoom.us
    ├── content_teams.js            ← injected into teams.microsoft.com
    ├── content_common.js           ← shared caption logic across all platforms
    ├── popup.html                  ← extension popup
    ├── popup.js                    ← popup logic
    ├── popup.css                   ← popup styles
    └── icon.png                    ← 128x128 icon
```

---

## .ENV.EXAMPLE

```env
# ── LLM (Featherless — OpenAI compatible) ─────────────────────────────────────
FEATHERLESS_API_KEY=rc_95744f33c4627acd1ff90f4e150a4458e4a1ee036c6ea3c6a7159c889a910eb3
FEATHERLESS_BASE_URL=https://api.featherless.ai/v1
FEATHERLESS_MODEL_MAIN=meta-llama/Meta-Llama-3.1-70B-Instruct
FEATHERLESS_MODEL_FAST=meta-llama/Llama-3.1-8B-Instruct

# ── Notion (ALL reports go here) ──────────────────────────────────────────────
NOTION_TOKEN=your_notion_integration_token
NOTION_PARENT_PAGE_ID=your_parent_page_id

# These are AUTO-CREATED by the agent on first run — leave blank
NOTION_COMMITMENTS_DB_ID=
NOTION_MEETINGS_DB_ID=
NOTION_PEOPLE_DB_ID=
NOTION_AGENDA_DB_ID=

# ── Notifications ──────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# ── Calendar (optional) ───────────────────────────────────────────────────────
GOOGLE_CALENDAR_CREDS=agent/credentials.json

# ── Agent behaviour ───────────────────────────────────────────────────────────
MOCK_MODE=false
AGENT_PORT=8000
WATCH_INTERVAL_SECONDS=10
NUDGE_HOURS_BEFORE=24
ESCALATE_HOURS_BEFORE=6
QUIET_HOURS_START=22
QUIET_HOURS_END=8
EXAM_MODE=false
```

---

## REQUIREMENTS.TXT

```
fastapi==0.111.0
uvicorn==0.29.0
python-dotenv==1.0.1
openai==1.30.0
requests==2.31.0
twilio==9.0.5
notion-client==2.2.2
apscheduler==3.10.4
google-auth==2.29.0
google-auth-oauthlib==1.2.0
google-api-python-client==2.127.0
python-multipart==0.0.9
websockets==12.0
```

---

## agent/llm.py  ← SINGLE WRAPPER FOR ALL LLM CALLS

```python
"""
All LLM calls go through this file.
Featherless is OpenAI-compatible — we use the openai SDK with a custom base_url.
Two models:
  MAIN  — Meta-Llama-3.1-70B — extraction, resolution, reports, agenda matching
  FAST  — Llama-3.1-8B      — nudge messages, quick checks (lower latency)
"""
import os, json
from openai import OpenAI
from mock_mode import MOCK_RESPONSES

MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

_client = OpenAI(
    base_url=os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"),
    api_key=os.getenv("FEATHERLESS_API_KEY", ""),
)

MODEL_MAIN = os.getenv("FEATHERLESS_MODEL_MAIN", "meta-llama/Meta-Llama-3.1-70B-Instruct")
MODEL_FAST = os.getenv("FEATHERLESS_MODEL_FAST", "meta-llama/Llama-3.1-8B-Instruct")


def call(system: str, user: str, model: str = None,
         temperature: float = 0.1, max_tokens: int = 2000,
         expect_json: bool = True) -> str:
    """
    Core LLM call. Returns raw string content.
    Caller is responsible for JSON parsing.
    """
    if MOCK:
        return MOCK_RESPONSES.get("default", "{}")

    m = model or MODEL_MAIN
    kwargs = dict(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    # Featherless supports response_format for Llama models
    if expect_json:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def call_fast(system: str, user: str,
              temperature: float = 0.7, max_tokens: int = 300,
              expect_json: bool = False) -> str:
    """Use the fast/small model for simple text generation."""
    return call(system, user, model=MODEL_FAST,
                temperature=temperature, max_tokens=max_tokens,
                expect_json=expect_json)


def parse_json(raw: str) -> list | dict:
    """Safe JSON parse — strips markdown fences if present."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
```

---

## agent/prompts.py

```python
# Every prompt is a named constant. Never bury prompts in business logic.

EXTRACTION_PROMPT = """
You are an autonomous commitment-extraction agent for meeting transcripts.
Parse the transcript and return a JSON array of commitment objects.
Skip ANYTHING that is a vague intention with no owner and no real deadline.

Each object MUST have ALL these fields:
{
  "speaker":           "name as spoken in transcript",
  "commitment_text":   "verbatim quote — exact words spoken",
  "normalized_task":   "clean 5-10 word action description",
  "explicit_deadline": "exact deadline phrase if stated, else null",
  "deadline_clue":     "contextual hint if no explicit date, else null",
  "depends_on_hint":   "phrase showing dependency on another task, else null",
  "beneficiary":       "person who is waiting on this, else null",
  "owner_type":        "person | ownerless | vague_intention",
  "item_type":         "self_commitment | assignment | meeting_request",
  "assigned_by":       "speaker name if assignment else null",
  "confidence":        0.0 to 1.0,
  "timestamp_sec":     integer seconds into transcript
}

CLASSIFICATION RULES:
owner_type "person"           → one named person takes clear responsibility
owner_type "ownerless"        → "we'll", "someone should", "the team will", "let's"
owner_type "vague_intention"  → no deadline, no owner → SKIP, do not include

item_type "self_commitment"   → person commits for themselves
item_type "assignment"        → speaker assigns TO someone else (owner = assignee)
item_type "meeting_request"   → proposing a future meeting

FEW-SHOT EXAMPLES:
"I'll finish the API by Thursday"
→ person, self_commitment, confidence 0.95 ✓ INCLUDE

"we should probably look into caching sometime"
→ vague_intention → SKIP, DO NOT INCLUDE

"we'll handle deployment"
→ ownerless, self_commitment ✓ INCLUDE (flag for owner assignment)

"once Alice finishes, I'll do the integration"
→ depends_on_hint: "once Alice finishes" ✓ INCLUDE

"Priya, can you review the contract by Friday?"
→ person, assignment, owner=Priya, assigned_by=[speaker] ✓ INCLUDE

"let's grab 15 min Thursday to sort this out"
→ meeting_request, explicit_deadline: "Thursday" ✓ INCLUDE

Attendees in this meeting: {attendees}

Return ONLY valid JSON array. No markdown. No explanation. No preamble.
"""

RESOLUTION_PROMPT = """
Resolve implicit or vague deadline references to ISO 8601 timestamps.

Current datetime: {current_datetime}
Calendar context (upcoming events): {calendar_json}

Rules:
- "before the client call" → find that event in calendar, set deadline = 1h before
- "end of week" → Friday 6 PM
- "end of day" → today 6 PM  
- "next week" → Monday 9 AM of next week
- "ASAP" or "soon" → current_datetime + 24h, confidence penalty -0.2
- "Thursday" → nearest upcoming Thursday at 6 PM
- unresolvable → deadline: null, needs_clarification: true

Input commitments: {commitments_json}

Add to each object:
  "deadline": "ISO 8601 or null"
  "needs_clarification": true | false

Return ONLY the updated JSON array.
"""

NUDGE_PROMPT = """
Write a short nudge message from a colleague to {owner}.
Warm, human tone. Like a helpful teammate, not a system alert or bot.

Context:
- Their exact words from the meeting: "{commitment_text}"
- Meeting name: {meeting_title}  
- Deadline: {deadline}
- Hours until deadline: {hours_until}

Rules:
- Quote their own words back to them naturally
- Under 80 words
- Do NOT start with "Reminder:" or "ALERT:" or "This is a notification"
- End with one concrete action they can take right now
- Sound like a person

Return ONLY the message text. Nothing else.
"""

AGENDA_MATCH_PROMPT = """
Check which agenda slots a meeting transcript chunk covers.

Meeting type: {meeting_type}
Pending agenda slots: {slots_json}
Transcript chunk (last 30 seconds): {chunk}

For each slot, return its coverage status:
[
  {
    "slot_id": "blockers",
    "status": "covered | pending | partial",
    "evidence_quote": "exact phrase from chunk proving coverage, or null"
  }
]

Return ONLY valid JSON array.
"""

PATTERN_REPORT_PROMPT = """
Generate a private coaching summary for a team lead.
This is NOT public — it goes to a private Notion page.

Team stats: {stats_json}

Write 3-4 sentences:
1. Overall team follow-through health
2. Who is most at risk of overcommitment (specific name)
3. One concrete structural suggestion to improve
4. Highlight anyone with perfect follow-through (positive reinforcement)

Frame as coaching, never blame. Never use "failed" or "missed".
Use "renegotiated" instead of "broke promise".

Return only the paragraph text.
"""

REASSIGNMENT_PROMPT = """
Someone is overloaded and a task may need reassigning.

Overloaded: {owner} — {open_count} open items, completes ~{rate}/week historically
Task to reassign: {task}
Available teammates with capacity: {available_json}

Write ONE sentence for the team lead:
- Name the specific person to reassign to
- Say why they're a good fit (skills match or capacity)
- Be specific and actionable

Return only that sentence.
"""

MOM_PROMPT = """
Write professional meeting minutes from this transcript and commitment data.

Meeting: {title}
Date: {date}
Attendees: {attendees}
Transcript: {transcript}
Extracted commitments: {commitments_json}
Agenda coverage: {agenda_json}

Format exactly as:

## Summary
[2-3 sentence overview of what was discussed and decided]

## Key Decisions
[bullet points — only real decisions, not discussion]

## Action Items
| Owner | Task | Deadline | Depends On | Status |
|-------|------|----------|------------|--------|
[one row per commitment]

## Ownerless Items (Need Assignment)
[list any ownerless commitments that still need an owner]

## Missed Agenda Items
[any required agenda slots that were not covered]

## Next Meeting
[if a follow-up was proposed, state it here]

Be concise. Professional. No filler.
"""

CROSS_MEETING_BRIEF_PROMPT = """
Generate a "since we last spoke" pre-meeting briefing.

New meeting attendees: {attendees}
Their open commitments from prior meetings: {open_items_json}
Flags (repeated promises, overdue items): {flags_json}

Write exactly 5 bullet points maximum that the meeting chair reads aloud.
Focus on:
• What was promised last time and is still open
• What is overdue or at risk
• Anyone who has promised the same thing twice without delivering

Each bullet under 20 words. Start each with "•".
Return only the bullets.
"""
```

---

## agent/models.py

```python
import sqlite3, json, os
from datetime import datetime

DB_PATH = "meeting_debt.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meetings (
        id              TEXT PRIMARY KEY,
        title           TEXT NOT NULL,
        type            TEXT DEFAULT 'club_meeting',
        platform        TEXT DEFAULT 'unknown',
        date            TEXT NOT NULL,
        owner           TEXT DEFAULT '',
        attendees       TEXT DEFAULT '[]',
        transcript      TEXT DEFAULT '',
        pre_brief       TEXT DEFAULT '',
        mom             TEXT DEFAULT '',
        status          TEXT DEFAULT 'active',
        notion_page_id  TEXT DEFAULT '',
        created_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitments (
        id                  TEXT PRIMARY KEY,
        meeting_id          TEXT NOT NULL,
        owner               TEXT NOT NULL,
        beneficiary         TEXT DEFAULT '',
        commitment_text     TEXT NOT NULL,
        normalized_task     TEXT NOT NULL,
        explicit_deadline   TEXT DEFAULT '',
        deadline            TEXT DEFAULT '',
        original_deadline   TEXT DEFAULT '',
        deadline_clue       TEXT DEFAULT '',
        status              TEXT DEFAULT 'open',
        owner_type          TEXT DEFAULT 'person',
        item_type           TEXT DEFAULT 'self_commitment',
        assigned_by         TEXT DEFAULT '',
        confidence          REAL DEFAULT 0.9,
        depends_on          TEXT DEFAULT '',
        nudge_count         INTEGER DEFAULT 0,
        timestamp_sec       INTEGER DEFAULT 0,
        warning             TEXT DEFAULT '',
        notion_page_id      TEXT DEFAULT '',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitment_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_id   TEXT NOT NULL,
        event           TEXT NOT NULL,
        detail          TEXT DEFAULT '',
        at              TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS agenda_state (
        meeting_id      TEXT NOT NULL,
        slot_id         TEXT NOT NULL,
        label           TEXT NOT NULL,
        required        INTEGER DEFAULT 1,
        status          TEXT DEFAULT 'pending',
        evidence_quote  TEXT DEFAULT '',
        covered_at      TEXT DEFAULT '',
        PRIMARY KEY (meeting_id, slot_id)
    );

    CREATE TABLE IF NOT EXISTS person_stats (
        person                  TEXT PRIMARY KEY,
        committed               INTEGER DEFAULT 0,
        on_time                 INTEGER DEFAULT 0,
        renegotiated            INTEGER DEFAULT 0,
        missed                  INTEGER DEFAULT 0,
        avg_completion_per_week REAL DEFAULT 2.0,
        notion_page_id          TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS calendar_drafts (
        id              TEXT PRIMARY KEY,
        commitment_id   TEXT NOT NULL,
        summary         TEXT NOT NULL,
        start_iso       TEXT NOT NULL,
        duration_min    INTEGER DEFAULT 15,
        attendees       TEXT DEFAULT '[]',
        status          TEXT DEFAULT 'pending',
        created_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS agent_clock (
        id              INTEGER PRIMARY KEY CHECK (id=1),
        simulated_now   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notion_ids (
        key             TEXT PRIMARY KEY,
        notion_id       TEXT NOT NULL
    );
    """)

    conn.execute(
        "INSERT OR IGNORE INTO agent_clock (id, simulated_now) VALUES (1, ?)",
        (datetime.utcnow().isoformat(),)
    )

    # Seed demo people with realistic history
    for row in [
        ("Alice",  8, 6, 1, 1, 3.0),
        ("Bob",    6, 3, 1, 2, 1.5),
        ("Rohith", 10,4, 2, 4, 2.0),
        ("Priya",  7, 7, 0, 0, 3.5),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO person_stats "
            "(person,committed,on_time,renegotiated,missed,avg_completion_per_week) "
            "VALUES (?,?,?,?,?,?)", row
        )
    conn.commit()
    conn.close()

def get_agent_now():
    conn = get_db()
    row  = conn.execute("SELECT simulated_now FROM agent_clock WHERE id=1").fetchone()
    conn.close()
    return datetime.fromisoformat(row["simulated_now"])

def advance_clock(hours: float) -> str:
    from datetime import timedelta
    new = (get_agent_now() + timedelta(hours=hours)).isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=? WHERE id=1", (new,))
    conn.commit(); conn.close()
    return new

def log_event(commitment_id: str, event: str, detail: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO commitment_history (commitment_id,event,detail,at) VALUES (?,?,?,?)",
        (commitment_id, event, detail, datetime.utcnow().isoformat())
    )
    conn.commit(); conn.close()

def set_notion_id(key: str, notion_id: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO notion_ids (key,notion_id) VALUES (?,?)",
                 (key, notion_id))
    conn.commit(); conn.close()

def get_notion_id(key: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT notion_id FROM notion_ids WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["notion_id"] if row else ""
```

---

## agent/notion_reporter.py  ← ALL NOTION WRITES

```python
"""
ALL Notion output lives here.
Creates and maintains 4 Notion databases under one parent page:
  1. Meetings          — one page per meeting, with MoM embedded
  2. Commitments       — one page per commitment, live status
  3. People            — per-person stats and coaching summary
  4. Agenda Coverage   — per-meeting agenda checklist

Every write is fire-and-forget (non-fatal if it fails).
"""
import os, json, requests
from datetime import datetime
from models import get_db, get_notion_id, set_notion_id

TOKEN    = os.getenv("NOTION_TOKEN", "")
PARENT   = os.getenv("NOTION_PARENT_PAGE_ID", "")
HEADERS  = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
    "Notion-Version":"2022-06-28"
}

# ── Database IDs (stored in SQLite after first-run creation) ──────────────────

def _db(key):
    env_map = {
        "meetings":    "NOTION_MEETINGS_DB_ID",
        "commitments": "NOTION_COMMITMENTS_DB_ID",
        "people":      "NOTION_PEOPLE_DB_ID",
        "agenda":      "NOTION_AGENDA_DB_ID",
    }
    env_val = os.getenv(env_map.get(key, ""), "")
    return env_val or get_notion_id(f"notion_db_{key}")

def _post(path, payload):
    try:
        r = requests.post(
            f"https://api.notion.com/v1/{path}",
            headers=HEADERS, json=payload, timeout=8
        )
        if r.status_code not in (200, 201):
            print(f"[Notion] {path} → {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    except Exception as e:
        print(f"[Notion] request failed (non-fatal): {e}")
        return None

def _patch(path, payload):
    try:
        r = requests.patch(
            f"https://api.notion.com/v1/{path}",
            headers=HEADERS, json=payload, timeout=8
        )
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[Notion] patch failed (non-fatal): {e}")
        return None

# ── First-run: create all databases ──────────────────────────────────────────

def setup_notion_workspace():
    """
    Call once on startup. Creates 4 databases in Notion under NOTION_PARENT_PAGE_ID.
    IDs are stored in SQLite so they persist across restarts.
    """
    if not TOKEN or not PARENT:
        print("[Notion] No token/parent — skipping setup")
        return

    _ensure_db("meetings", {
        "Name":        {"title": {}},
        "Type":        {"select": {}},
        "Platform":    {"select": {}},
        "Date":        {"date": {}},
        "Owner":       {"rich_text": {}},
        "Status":      {"select": {"options": [
            {"name":"active","color":"blue"},
            {"name":"finalized","color":"green"},
        ]}},
        "Commitments": {"number": {}},
        "Follow Through": {"number": {}},
    })

    _ensure_db("commitments", {
        "Task":         {"title": {}},
        "Owner":        {"select": {}},
        "Deadline":     {"date": {}},
        "Status":       {"select": {"options": [
            {"name":"open","color":"blue"},
            {"name":"nudged","color":"yellow"},
            {"name":"escalated","color":"orange"},
            {"name":"done","color":"green"},
            {"name":"missed","color":"red"},
            {"name":"renegotiated","color":"purple"},
            {"name":"reassigned","color":"gray"},
            {"name":"review","color":"pink"},
        ]}},
        "Confidence":   {"select": {"options": [
            {"name":"high","color":"green"},
            {"name":"medium","color":"yellow"},
            {"name":"low","color":"red"},
        ]}},
        "Meeting":      {"rich_text": {}},
        "Verbatim":     {"rich_text": {}},
        "Depends On":   {"rich_text": {}},
        "Beneficiary":  {"rich_text": {}},
        "Owner Type":   {"select": {"options": [
            {"name":"person","color":"blue"},
            {"name":"ownerless","color":"orange"},
        ]}},
        "Nudges Sent":  {"number": {}},
        "Warning":      {"rich_text": {}},
    })

    _ensure_db("people", {
        "Name":              {"title": {}},
        "Committed":         {"number": {}},
        "On Time":           {"number": {}},
        "Renegotiated":      {"number": {}},
        "Missed":            {"number": {}},
        "Follow Through %":  {"number": {}},
        "Weekly Capacity":   {"number": {}},
        "At Risk":           {"checkbox": {}},
        "Coaching Note":     {"rich_text": {}},
    })

    _ensure_db("agenda", {
        "Slot":        {"title": {}},
        "Meeting":     {"rich_text": {}},
        "Required":    {"checkbox": {}},
        "Status":      {"select": {"options": [
            {"name":"pending","color":"gray"},
            {"name":"covered","color":"green"},
            {"name":"missed","color":"red"},
        ]}},
        "Evidence":    {"rich_text": {}},
    })

    print("[Notion] Workspace setup complete — all 4 databases ready")

def _ensure_db(name: str, properties: dict):
    existing = _db(name)
    if existing:
        print(f"[Notion] {name} DB already exists: {existing[:8]}...")
        return existing

    result = _post("databases", {
        "parent": {"type": "page_id", "page_id": PARENT},
        "title":  [{"type": "text", "text": {"content": f"MDC — {name.title()}"}}],
        "properties": properties
    })
    if result:
        db_id = result["id"]
        set_notion_id(f"notion_db_{name}", db_id)
        print(f"[Notion] Created {name} database: {db_id[:8]}...")
        return db_id
    return None

# ── Meeting pages ─────────────────────────────────────────────────────────────

def create_meeting_page(meeting: dict) -> str:
    """Create a Notion page for a new meeting. Returns page ID."""
    db = _db("meetings")
    if not db: return ""

    result = _post("pages", {
        "parent": {"database_id": db},
        "properties": {
            "Name":     {"title": [{"text": {"content": meeting.get("title","Untitled")}}]},
            "Type":     {"select": {"name": meeting.get("type","club_meeting")}},
            "Platform": {"select": {"name": meeting.get("platform","unknown")}},
            "Date":     {"date": {"start": meeting.get("date", datetime.utcnow().isoformat())}},
            "Owner":    {"rich_text": [{"text": {"content": meeting.get("owner","")}}]},
            "Status":   {"select": {"name": "active"}},
            "Commitments": {"number": 0},
        }
    })
    return result["id"] if result else ""

def update_meeting_page(page_id: str, updates: dict):
    """Update meeting page properties and optionally append MoM as page content."""
    if not page_id: return

    props = {}
    if "status" in updates:
        props["Status"] = {"select": {"name": updates["status"]}}
    if "commitments_count" in updates:
        props["Commitments"] = {"number": updates["commitments_count"]}
    if "follow_through" in updates:
        props["Follow Through"] = {"number": updates["follow_through"]}

    if props:
        _patch(f"pages/{page_id}", {"properties": props})

    # Append MoM as page body
    if "mom" in updates and updates["mom"]:
        _post(f"blocks/{page_id}/children", {
            "children": [
                {"object": "block", "type": "heading_2",
                 "heading_2": {"rich_text": [{"text": {"content": "Minutes of Meeting"}}]}},
                *[
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"text": {"content": line}}]}}
                    for line in updates["mom"].split("\n")[:100]   # Notion block limit
                    if line.strip()
                ]
            ]
        })

    # Append agenda coverage
    if "agenda" in updates:
        slots = updates["agenda"].get("slots", [])
        if slots:
            rows = [{"object":"block","type":"heading_3",
                     "heading_3":{"rich_text":[{"text":{"content":"Agenda Coverage"}}]}}]
            for s in slots:
                icon = "✅" if s["status"] == "covered" else "❌" if s["required"] else "⬜"
                rows.append({
                    "object":"block","type":"bulleted_list_item",
                    "bulleted_list_item":{"rich_text":[
                        {"text":{"content": f"{icon} {s['label']} — {s['status']}"}}
                    ]}
                })
            _post(f"blocks/{page_id}/children", {"children": rows[:50]})

# ── Commitment pages ──────────────────────────────────────────────────────────

def create_commitment_page(c: dict, meeting_title: str) -> str:
    """Create a Notion page for a commitment. Returns page ID."""
    db = _db("commitments")
    if not db: return ""

    conf = c.get("confidence", 0.9)
    conf_label = "high" if conf >= 0.8 else "medium" if conf >= 0.5 else "low"

    result = _post("pages", {
        "parent": {"database_id": db},
        "properties": {
            "Task":        {"title": [{"text": {"content": c.get("normalized_task","?")}}]},
            "Owner":       {"select": {"name": c.get("owner","Unknown")}},
            "Deadline":    {"date": {"start": c["deadline"]} if c.get("deadline") else None},
            "Status":      {"select": {"name": c.get("status","open")}},
            "Confidence":  {"select": {"name": conf_label}},
            "Meeting":     {"rich_text": [{"text":{"content": meeting_title}}]},
            "Verbatim":    {"rich_text": [{"text":{"content": c.get("commitment_text","")}}]},
            "Depends On":  {"rich_text": [{"text":{"content": c.get("depends_on","")}}]},
            "Beneficiary": {"rich_text": [{"text":{"content": c.get("beneficiary","")}}]},
            "Owner Type":  {"select": {"name": c.get("owner_type","person")}},
            "Nudges Sent": {"number": 0},
            "Warning":     {"rich_text": [{"text":{"content": c.get("warning","")}}]},
        }
    })
    page_id = result["id"] if result else ""

    # Add provenance block: verbatim quote + timestamp
    if page_id and c.get("commitment_text"):
        _post(f"blocks/{page_id}/children", {"children": [
            {"object":"block","type":"quote",
             "quote":{"rich_text":[{"text":{"content":
                 f"\"{c['commitment_text']}\" — {c.get('speaker','?')} "
                 f"@ {c.get('timestamp_sec',0)}s"
             }}]}},
        ]})

    return page_id

def update_commitment_status(page_id: str, status: str,
                              nudge_count: int = None, detail: str = ""):
    """Update a commitment's status in Notion."""
    if not page_id: return
    props = {"Status": {"select": {"name": status}}}
    if nudge_count is not None:
        props["Nudges Sent"] = {"number": nudge_count}
    _patch(f"pages/{page_id}", {"properties": props})
    if detail:
        _post(f"blocks/{page_id}/children", {"children": [
            {"object":"block","type":"callout",
             "callout":{"rich_text":[{"text":{"content":
                 f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] {detail}"
             }}],"icon":{"emoji":"📌"}}}
        ]})

# ── People / pattern report ───────────────────────────────────────────────────

def upsert_person_page(stats: dict, coaching_note: str = ""):
    """Create or update a person's page in the People database."""
    db = _db("people")
    if not db: return

    total = stats.get("committed", 0) or 1
    follow_through = round(stats.get("on_time", 0) / total * 100, 1)
    at_risk = follow_through < 50 and stats.get("committed", 0) >= 3

    # Check if page already exists
    existing_id = stats.get("notion_page_id", "")

    props = {
        "Name":             {"title": [{"text":{"content": stats["person"]}}]},
        "Committed":        {"number": stats.get("committed", 0)},
        "On Time":          {"number": stats.get("on_time", 0)},
        "Renegotiated":     {"number": stats.get("renegotiated", 0)},
        "Missed":           {"number": stats.get("missed", 0)},
        "Follow Through %": {"number": follow_through},
        "Weekly Capacity":  {"number": stats.get("avg_completion_per_week", 2.0)},
        "At Risk":          {"checkbox": at_risk},
        "Coaching Note":    {"rich_text": [{"text":{"content": coaching_note[:2000]}}]},
    }

    if existing_id:
        _patch(f"pages/{existing_id}", {"properties": props})
    else:
        result = _post("pages", {"parent":{"database_id":db}, "properties": props})
        if result:
            conn = get_db()
            conn.execute("UPDATE person_stats SET notion_page_id=? WHERE person=?",
                         (result["id"], stats["person"]))
            conn.commit(); conn.close()

def create_pattern_report_page(summary: str, stats: list,
                                debt_scores: list) -> str:
    """Create a full pattern report page under the parent Notion page."""
    if not PARENT: return ""

    result = _post("pages", {
        "parent": {"page_id": PARENT},
        "properties": {
            "title": [{"text":{"content":
                f"Pattern Report — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            }}]
        },
        "children": [
            {"object":"block","type":"heading_1",
             "heading_1":{"rich_text":[{"text":{"content":"Team Commitment Health Report"}}]}},
            {"object":"block","type":"paragraph",
             "paragraph":{"rich_text":[{"text":{"content": summary}}]}},
            {"object":"block","type":"divider","divider":{}},
            {"object":"block","type":"heading_2",
             "heading_2":{"rich_text":[{"text":{"content":"Per-Person Stats"}}]}},
            *[{
                "object":"block","type":"bulleted_list_item",
                "bulleted_list_item":{"rich_text":[{"text":{"content":
                    f"{'⚡' if s.get('at_risk') else '✅'} {s['person']} — "
                    f"{s.get('on_time',0)}/{s.get('committed',0)} on time "
                    f"({round(s.get('on_time',0)/(s.get('committed',0) or 1)*100)}%)"
                }}]}
            } for s in stats],
            {"object":"block","type":"divider","divider":{}},
            {"object":"block","type":"heading_2",
             "heading_2":{"rich_text":[{"text":{"content":"Meeting Debt Scores"}}]}},
            *[{
                "object":"block","type":"bulleted_list_item",
                "bulleted_list_item":{"rich_text":[{"text":{"content":
                    f"{'🔄' if m.get('suggest_async') else '📋'} {m['title']}: "
                    f"{round(m.get('rate',0)*100)}% follow-through"
                    f"{' — consider async' if m.get('suggest_async') else ''}"
                }}]}
            } for m in debt_scores[:10]],
        ]
    })
    return result["id"] if result else ""

# ── Agenda ────────────────────────────────────────────────────────────────────

def log_agenda_slot(meeting_id: str, slot: dict):
    """Log an agenda slot's coverage status to Notion."""
    db = _db("agenda")
    if not db: return
    _post("pages", {
        "parent": {"database_id": db},
        "properties": {
            "Slot":     {"title": [{"text":{"content": slot.get("label","?")}}]},
            "Meeting":  {"rich_text": [{"text":{"content": meeting_id[:8]}}]},
            "Required": {"checkbox": bool(slot.get("required"))},
            "Status":   {"select": {"name": slot.get("status","pending")}},
            "Evidence": {"rich_text": [{"text":{"content":
                slot.get("evidence_quote","")[:2000]
            }}]},
        }
    })
```

---

## agent/extractor.py

```python
import uuid, json
from datetime import datetime
from llm import call, parse_json
from prompts import EXTRACTION_PROMPT
from mock_mode import MOCK_COMMITMENTS

def extract(transcript: str, attendees: list, meeting_id: str) -> list:
    if not transcript.strip():
        return []

    raw = call(
        system=EXTRACTION_PROMPT.format(
            attendees=", ".join(a.get("name","?") for a in attendees)
        ),
        user=f"TRANSCRIPT:\n{transcript}",
        temperature=0.1,
        max_tokens=3000,
        expect_json=True
    )

    try:
        items = parse_json(raw)
        if isinstance(items, dict):
            items = list(items.values())[0]
    except Exception as e:
        print(f"[Extractor] parse failed: {e}\nRaw: {raw[:300]}")
        items = []

    # Filter vague intentions
    real = [c for c in items if c.get("owner_type") != "vague_intention"]

    # Stamp IDs
    now = datetime.utcnow().isoformat()
    for c in real:
        c.setdefault("id", str(uuid.uuid4()))
        c["meeting_id"]  = meeting_id
        c["status"]      = "review" if c.get("confidence",1.0) < 0.8 else "open"
        c["nudge_count"] = 0
        c["created_at"]  = now
        c["updated_at"]  = now

    return real
```

---

## agent/resolver.py

```python
import json
from llm import call, parse_json
from prompts import RESOLUTION_PROMPT
from models import get_agent_now

DEMO_CALENDAR = [
    {"title": "Client Call",   "datetime": "2026-08-05T15:00:00"},
    {"title": "Sprint Review", "datetime": "2026-08-07T11:00:00"},
    {"title": "Friday Demo",   "datetime": "2026-08-08T17:00:00"},
]

def resolve(commitments: list, calendar: list = None) -> list:
    needs = [c for c in commitments
             if c.get("deadline_clue") or c.get("explicit_deadline")]
    if not needs:
        return commitments

    cal = calendar or DEMO_CALENDAR
    raw = call(
        system=RESOLUTION_PROMPT.format(
            current_datetime=get_agent_now().isoformat(),
            calendar_json=json.dumps(cal),
            commitments_json=json.dumps(needs)
        ),
        user="Resolve the deadlines.",
        temperature=0.0,
        max_tokens=2000,
        expect_json=True
    )

    try:
        resolved = parse_json(raw)
        if isinstance(resolved, dict):
            resolved = list(resolved.values())[0]
        rmap = {r["id"]: r for r in resolved}
        for c in commitments:
            if c["id"] in rmap:
                c.update(rmap[c["id"]])
            if not c.get("original_deadline") and c.get("deadline"):
                c["original_deadline"] = c["deadline"]
    except Exception as e:
        print(f"[Resolver] failed: {e}")

    return commitments
```

---

## agent/similarity.py

```python
"""
THREE outcomes from ONE engine:
  new        → insert as fresh commitment
  merge      → duplicate across meetings
  renegotiate→ speaker modified existing open commitment
  recommit   → same promise made again after it was missed
"""
from models import get_db

THRESHOLD = 0.65

RENEG_PHRASES = [
    "push that to","push this to","move it to","delay","next week",
    "next sprint","won't make","can't make","let's extend","actually",
    "I'll do half","partial","by end of","actually let's"
]

def _jaccard(a: str, b: str) -> float:
    s1, s2 = set(a.lower().split()), set(b.lower().split())
    if not s1 or not s2: return 0.0
    return len(s1 & s2) / len(s1 | s2)

def classify(new: dict) -> dict:
    conn  = get_db()
    rows  = conn.execute("""
        SELECT id, owner, normalized_task, status
        FROM commitments
        WHERE status IN ('open','nudged','escalated','missed')
    """).fetchall()
    conn.close()

    task  = new.get("normalized_task","")
    owner = new.get("owner","").lower()
    text  = new.get("commitment_text","").lower()

    best, best_score = None, 0.0
    for r in rows:
        score = _jaccard(task, r["normalized_task"])
        if r["owner"].lower() == owner:
            score *= 1.25
        if score > best_score:
            best_score, best = score, r

    if best_score < THRESHOLD or not best:
        return {"action":"new"}

    if any(p in text for p in RENEG_PHRASES):
        return {"action":"renegotiate","target_id":best["id"],
                "new_deadline":new.get("deadline")}

    if best["status"] == "missed":
        return {"action":"recommit","target_id":best["id"],
                "warning":f"This was committed before and missed. Second promise flagged."}

    return {"action":"merge","target_id":best["id"]}
```

---

## agent/nudger.py

```python
import os, requests
from twilio.rest import Client as Twilio
from llm import call_fast
from prompts import NUDGE_PROMPT, REASSIGNMENT_PROMPT
from models import get_db
from notion_reporter import update_commitment_status

SLACK   = os.getenv("SLACK_WEBHOOK_URL","")
WA_FROM = os.getenv("TWILIO_WHATSAPP_FROM","")
WA_TO   = os.getenv("TWILIO_WHATSAPP_TO","")
MOCK    = os.getenv("MOCK_MODE","false").lower() == "true"

def _gen_nudge(c: dict, hours_until: float) -> str:
    return call_fast(
        system="You write friendly nudge messages from colleagues.",
        user=NUDGE_PROMPT.format(
            owner=c["owner"],
            commitment_text=c["commitment_text"],
            meeting_title=c.get("meeting_title","your meeting"),
            deadline=c.get("deadline",""),
            hours_until=round(hours_until,1)
        ),
        temperature=0.7,
        max_tokens=150,
        expect_json=False
    )

def _whatsapp(text: str) -> bool:
    if not WA_TO or MOCK: return False
    try:
        Twilio(os.getenv("TWILIO_ACCOUNT_SID"),
               os.getenv("TWILIO_AUTH_TOKEN")
               ).messages.create(body=f"🔔 {text}", from_=WA_FROM, to=WA_TO)
        return True
    except Exception as e:
        print(f"[WhatsApp] {e}"); return False

def _slack(text: str, color: str = "#FFA500"):
    if not SLACK: return
    try:
        requests.post(SLACK,
                      json={"attachments":[{"color":color,"text":text}]},
                      timeout=4)
    except Exception as e:
        print(f"[Slack] {e}")

def _deliver(text: str, color: str = "#FFA500"):
    if not _whatsapp(text):
        _slack(text, color)

def send_nudge(c: dict, hours_until: float):
    msg = _gen_nudge(c, hours_until)
    _deliver(msg)
    update_commitment_status(
        c.get("notion_page_id",""), "nudged", c.get("nudge_count",0)+1,
        f"Nudge sent at T-{hours_until:.1f}h: {msg[:200]}"
    )

def send_escalation(c: dict):
    text = (f"⚠️ *Escalation* — {c['owner']} committed to "
            f"_{c.get('normalized_task','?')}_ and the deadline has passed.\n"
            f"Original: \"{c.get('commitment_text','')}\"")
    _deliver(text, "#E24B4A")
    update_commitment_status(c.get("notion_page_id",""), "escalated",
                              detail="Escalated to meeting owner")

def send_ownerless_alert(c: dict, meeting_owner: str):
    _slack(f"⚠️ *Ownerless Commitment Detected*\n"
           f"\"{c.get('commitment_text','')}\"\n"
           f"No owner assigned. {meeting_owner}, who's taking this?\n"
           f"POST /commitments/{c['id']}/action {{\"action\":\"assign_owner\","
           f"\"new_owner\":\"Name\"}}", "#FFA500")

def send_wrapup_alert(meeting_id: str, missed_slots: list):
    labels = ", ".join(s["label"] for s in missed_slots)
    _slack(f"📋 *Wrap-up Alert* (meeting `{meeting_id[:8]}`)\n"
           f"Before you close — required items not covered: {labels}", "#FFA500")

def send_cascade(c: dict, delay_h: float, upstream: str):
    _slack(f"🔗 *Cascade Shift* — {c['owner']}'s task "
           f"_{c.get('normalized_task','?')}_ shifted by {delay_h:.0f}h "
           f"because upstream task '{upstream}' slipped.", "#BA7517")

def send_recommit_warning(c: dict, warning: str):
    _slack(f"🔁 *Recommitment Detected*\n{warning}\n"
           f"Task: _{c.get('normalized_task','?')}_", "#534AB7")

def send_beneficiary_done(c: dict):
    if not c.get("beneficiary"): return
    _slack(f"✅ *For {c['beneficiary']}*: "
           f"{c['owner']} completed _{c.get('normalized_task','?')}_. Done!")
    update_commitment_status(c.get("notion_page_id",""), "done",
                              detail="Marked done — beneficiary notified")

def send_overcommit_warning(owner: str, open_count: int, rate: float):
    _slack(f"⚡ *Overcommitment Warning* — {owner} has {open_count} open items "
           f"(completes ~{rate}/week). Consider redistributing.", "#BA7517")

def send_reassignment(c: dict, open_count: int, rate: float):
    conn = get_db()
    avail = conn.execute("""
        SELECT p.person, p.avg_completion_per_week,
               COUNT(oc.id) as cur
        FROM person_stats p
        LEFT JOIN commitments oc
          ON oc.owner=p.person AND oc.status IN ('open','nudged')
        WHERE p.person!=?
        GROUP BY p.person
        HAVING cur < p.avg_completion_per_week
        ORDER BY cur ASC LIMIT 3
    """, (c["owner"],)).fetchall()
    conn.close()
    if not avail: return

    msg = call_fast(
        system="You suggest task reassignments concisely.",
        user=REASSIGNMENT_PROMPT.format(
            owner=c["owner"], open_count=open_count, rate=rate,
            available_json=[dict(a) for a in avail],
            task=c.get("normalized_task","?")
        ),
        expect_json=False
    )
    _slack(f"💡 *Redistribution Suggestion*\n{msg}", "#0F6E56")
```

---

## agent/scheduler.py

```python
"""
THE AUTONOMOUS CORE — pure deterministic rules, no LLM calls.
LLM is invoked ONLY inside nudger.py for message text generation.
"""
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import get_db, get_agent_now, log_event

NUDGE_H    = float(os.getenv("NUDGE_HOURS_BEFORE","24"))
ESCALATE_H = float(os.getenv("ESCALATE_HOURS_BEFORE","6"))
QH_START   = int(os.getenv("QUIET_HOURS_START","22"))
QH_END     = int(os.getenv("QUIET_HOURS_END","8"))
EXAM_MODE  = os.getenv("EXAM_MODE","false").lower() == "true"
INTERVAL   = int(os.getenv("WATCH_INTERVAL_SECONDS","10"))

_scheduler = BackgroundScheduler()

def start():
    _scheduler.add_job(tick, "interval", seconds=INTERVAL,
                       id="watch", replace_existing=True)
    _scheduler.start()
    print(f"[Scheduler] Watch loop started — ticking every {INTERVAL}s")

def stop():
    _scheduler.shutdown(wait=False)

def tick():
    now = get_agent_now()
    if _quiet(now): return

    conn = get_db()
    rows = conn.execute("""
        SELECT c.*, m.title as meeting_title, m.owner as meeting_owner
        FROM commitments c
        JOIN meetings m ON c.meeting_id=m.id
        WHERE c.status IN ('open','nudged','escalated')
          AND c.deadline IS NOT NULL AND c.deadline != ''
    """).fetchall()
    conn.close()

    for r in rows:
        c = dict(r)
        try:
            dl      = datetime.fromisoformat(c["deadline"])
            h_until = (dl - now).total_seconds() / 3600
        except:
            continue

        if h_until <= NUDGE_H and c["status"] == "open":
            from nudger import send_nudge
            send_nudge(c, h_until)
            _set(c["id"], "nudged")
            _inc_nudge(c["id"])
            log_event(c["id"], "nudged", f"T-{h_until:.1f}h")

        elif h_until <= ESCALATE_H and c["status"] == "nudged":
            from nudger import send_escalation
            send_escalation(c)
            _set(c["id"], "escalated")
            log_event(c["id"], "escalated")

        elif h_until < 0 and c["status"] in ("open","nudged","escalated"):
            _set(c["id"], "missed")
            log_event(c["id"], "missed", "deadline passed")
            _bump(c["owner"], "missed")
            cascade(c["id"], abs(h_until), c.get("normalized_task","?"))
            _check_reassignment(c)

def cascade(commitment_id: str, delay_h: float, upstream_task: str):
    """Propagate deadline slip to all downstream dependents recursively."""
    conn = get_db()
    deps = conn.execute("""
        SELECT * FROM commitments
        WHERE depends_on=? AND status IN ('open','nudged')
    """, (commitment_id,)).fetchall()
    conn.close()

    for dep in deps:
        d = dict(dep)
        try:
            new_dl = (datetime.fromisoformat(d["deadline"])
                      + timedelta(hours=delay_h)).isoformat()
        except: continue
        conn = get_db()
        conn.execute("UPDATE commitments SET deadline=?,updated_at=? WHERE id=?",
                     (new_dl, datetime.utcnow().isoformat(), d["id"]))
        conn.commit(); conn.close()
        from nudger import send_cascade
        send_cascade(d, delay_h, upstream_task)
        log_event(d["id"], "cascade_shifted", f"+{delay_h:.0f}h from {upstream_task}")
        cascade(d["id"], delay_h, d.get("normalized_task","?"))

def _check_reassignment(c: dict):
    conn = get_db()
    stat   = conn.execute("SELECT * FROM person_stats WHERE person=?",
                           (c["owner"],)).fetchone()
    open_n = conn.execute("""SELECT COUNT(*) as n FROM commitments
        WHERE owner=? AND status IN ('open','nudged','escalated')""",
        (c["owner"],)).fetchone()["n"]
    conn.close()
    if stat and open_n > stat["avg_completion_per_week"] * 1.5:
        from nudger import send_reassignment
        send_reassignment(c, open_n, stat["avg_completion_per_week"])

def _set(cid, status):
    conn = get_db()
    conn.execute("UPDATE commitments SET status=?,updated_at=? WHERE id=?",
                 (status, datetime.utcnow().isoformat(), cid))
    conn.commit(); conn.close()

def _inc_nudge(cid):
    conn = get_db()
    conn.execute("UPDATE commitments SET nudge_count=nudge_count+1 WHERE id=?", (cid,))
    conn.commit(); conn.close()

def _bump(person, field):
    conn = get_db()
    conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
    conn.commit(); conn.close()

def _quiet(now: datetime) -> bool:
    if EXAM_MODE: return True
    return now.hour >= QH_START or now.hour < QH_END
```

---

## agent/agenda.py

```python
import os, json, glob
from llm import call, parse_json
from prompts import AGENDA_MATCH_PROMPT
from models import get_db
from notion_reporter import log_agenda_slot

TEMPLATES = {}
WRAPUP_CUES = [
    "okay anything else","let's wrap","wrap up","that's all",
    "thanks everyone","any final","last thing","before we go","we'll close"
]

def load_templates():
    base = os.path.join(os.path.dirname(__file__), "templates")
    for path in glob.glob(f"{base}/*.json"):
        with open(path) as f:
            t = json.load(f)
            TEMPLATES[t["type"]] = t["slots"]

def init_for_meeting(meeting_id: str, meeting_type: str):
    slots = TEMPLATES.get(meeting_type, TEMPLATES.get("club_meeting", []))
    conn  = get_db()
    for s in slots:
        conn.execute(
            "INSERT OR IGNORE INTO agenda_state "
            "(meeting_id,slot_id,label,required,status) VALUES (?,?,?,?,'pending')",
            (meeting_id, s["id"], s["label"], 1 if s.get("required") else 0)
        )
    conn.commit(); conn.close()

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

    # Special: "owners" slot computed from commitments
    for s in pending:
        if s["slot_id"] == "owners":
            ownerless = [c for c in commitments if c.get("owner_type")=="ownerless"]
            if not ownerless:
                _cover(meeting_id, "owners", "All commitments have named owners")

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
                temperature=0.1, max_tokens=600, expect_json=True
            )
            results = parse_json(raw)
            if isinstance(results, dict): results = list(results.values())[0]
            for r in results:
                if r.get("status") == "covered":
                    _cover(meeting_id, r["slot_id"], r.get("evidence_quote",""))
        except Exception as e:
            print(f"[Agenda] match failed (non-fatal): {e}")

    # Wrapup detection
    is_wrap = any(cue in chunk.lower() for cue in WRAPUP_CUES)
    status  = get_status(meeting_id)
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
    slots  = [dict(r) for r in rows]
    missed = [s for s in slots if s["required"] and s["status"]=="pending"]
    return {"slots":slots, "missed_required":missed,
            "all_covered":len(missed)==0}

def _cover(meeting_id, slot_id, evidence):
    from datetime import datetime
    conn = get_db()
    conn.execute(
        "UPDATE agenda_state SET status='covered',evidence_quote=?,covered_at=? "
        "WHERE meeting_id=? AND slot_id=?",
        (evidence, datetime.utcnow().isoformat(), meeting_id, slot_id)
    )
    conn.commit(); conn.close()

    # Mirror to Notion
    log_agenda_slot(meeting_id, {
        "label": slot_id, "required": True,
        "status": "covered", "evidence_quote": evidence
    })
```

---

## agent/main.py

```python
import os, uuid, json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db, get_agent_now, advance_clock, log_event
from extractor import extract
from resolver import resolve
from similarity import classify
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
    allow_origins=["*","https://meet.google.com","https://zoom.us",
                   "https://teams.microsoft.com","chrome-extension://*"],
    allow_methods=["*"], allow_headers=["*"])

# ── Request models ─────────────────────────────────────────────────────────────

class MeetingStart(BaseModel):
    title:     str
    type:      str = "club_meeting"
    platform:  str = "unknown"
    owner:     str = ""
    attendees: List[dict] = []
    pre_brief: str = ""        # pre-meeting context / agenda items entered by user

class ChunkReq(BaseModel):
    chunk:       str
    chunk_index: int = 0

class ActionReq(BaseModel):
    action:       str
    new_deadline: Optional[str] = None
    new_owner:    Optional[str] = None

class PreBriefReq(BaseModel):
    attendees:      List[str]
    context_notes:  str = ""   # anything the user wants to pre-load

# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    load_templates()
    setup_notion_workspace()   # creates Notion DBs if not exist
    start_scheduler()
    print("[Agent] Running. Extension can now connect.")

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/meetings/start")
async def start_meeting(req: MeetingStart):
    """
    Called by extension when user starts capturing.
    Creates meeting in SQLite + Notion.
    Accepts optional pre-brief context (agenda, background info).
    """
    mid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Generate cross-meeting pre-brief if attendees provided
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
    conn.commit(); conn.close()

    init_for_meeting(mid, req.type)

    # Create Notion meeting page
    notion_page = create_meeting_page({
        "id": mid, "title": req.title, "type": req.type,
        "platform": req.platform, "date": now, "owner": req.owner
    })
    if notion_page:
        conn = get_db()
        conn.execute("UPDATE meetings SET notion_page_id=? WHERE id=?",
                     (notion_page, mid))
        conn.commit(); conn.close()

        # Write pre-brief to Notion page
        if pre_brief_text:
            from notion_reporter import _post
            _post(f"blocks/{notion_page}/children", {"children": [
                {"object":"block","type":"callout",
                 "callout":{"rich_text":[{"text":{"content":
                     f"Pre-meeting context:\n{pre_brief_text}"
                 }}],"icon":{"emoji":"📋"}}}
            ]})

    return {
        "meeting_id":  mid,
        "notion_page": notion_page,
        "pre_brief":   pre_brief_text
    }

@app.post("/meetings/{mid}/chunk")
async def ingest_chunk(mid: str, req: ChunkReq):
    """
    Called every 30s by the extension with the latest caption chunk.
    Full pipeline runs on each chunk.
    """
    conn = get_db()
    m    = conn.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m: raise HTTPException(404, "Meeting not found")
    m = dict(m)

    # Append chunk to full transcript
    conn = get_db()
    conn.execute("UPDATE meetings SET transcript=transcript||? WHERE id=?",
                 ("\n" + req.chunk, mid))
    conn.commit(); conn.close()

    attendees = json.loads(m["attendees"])

    raw      = extract(req.chunk, attendees, mid)
    resolved = resolve(raw)

    saved = []
    for c in resolved:
        result = _save_commitment(c, m["owner"], m.get("notion_page_id",""),
                                  m["title"])
        saved.append(result)

    all_c  = _all_commitments(mid)
    agenda = process_chunk(mid, m["type"], req.chunk, all_c)

    # Update Notion meeting page commitment count
    update_meeting_page(m.get("notion_page_id",""), {
        "commitments_count": len(all_c)
    })

    return {
        "meeting_id":             mid,
        "commitments_this_chunk": len([s for s in saved
                                       if s.get("action_taken")=="created"]),
        "total_commitments":      len(all_c),
        "agenda":                 agenda
    }

@app.post("/meetings/{mid}/end")
async def end_meeting(mid: str):
    """
    Called by extension when user clicks Stop Capturing.
    Generates MoM, posts full report to Notion, triggers pattern report.
    """
    conn = get_db()
    m    = conn.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m: raise HTTPException(404, "Meeting not found")
    m = dict(m)

    commitments = _all_commitments(mid)
    agenda      = get_status(mid)

    # Generate MoM
    mom = _gen_mom(m, commitments, agenda)

    # Update SQLite
    conn = get_db()
    conn.execute("UPDATE meetings SET mom=?,status='finalized' WHERE id=?",
                 (mom, mid))
    conn.commit(); conn.close()

    # Write everything to Notion
    notion_page = m.get("notion_page_id","")
    update_meeting_page(notion_page, {
        "status": "finalized",
        "mom": mom,
        "agenda": agenda,
        "commitments_count": len(commitments),
    })

    # Write agenda slots to Notion agenda DB
    for s in agenda["slots"]:
        from notion_reporter import log_agenda_slot
        log_agenda_slot(mid, s)

    # Pattern report
    report = _gen_pattern_report()
    create_pattern_report_page(
        report["summary"], report["stats"], report["debt"]
    )

    return {
        "meeting_id": mid,
        "commitments": len(commitments),
        "mom_generated": bool(mom),
        "missed_agenda": len(agenda["missed_required"]),
        "notion_page": notion_page
    }

@app.post("/meetings/{mid}/pre-brief")
async def get_pre_brief(mid: str, req: PreBriefReq):
    """
    Can be called BEFORE a meeting starts to generate a context brief.
    Also accepts free-text context notes from the user.
    """
    brief = _gen_pre_brief(req.attendees, req.context_notes)
    return {"brief": brief}

@app.post("/commitments/{cid}/action")
async def commitment_action(cid: str, req: ActionReq):
    """Human action — called from Slack/WhatsApp reply or direct POST."""
    conn = get_db()
    c    = conn.execute("SELECT * FROM commitments WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not c: raise HTTPException(404, "Commitment not found")
    c   = dict(c)
    now = datetime.utcnow().isoformat()

    if req.action == "done":
        _update_c(cid, {"status":"done","updated_at":now})
        send_beneficiary_done(c)
        _bump_stat(c["owner"], "on_time")
        log_event(cid, "done")

    elif req.action == "need_time":
        if not req.new_deadline: raise HTTPException(400,"new_deadline required")
        _update_c(cid, {"status":"renegotiated","deadline":req.new_deadline,
                         "updated_at":now})
        try:
            old_h = datetime.fromisoformat(c["deadline"])
            new_h = datetime.fromisoformat(req.new_deadline)
            dh    = (new_h - old_h).total_seconds() / 3600
            if dh > 0:
                cascade(cid, dh, c.get("normalized_task","?"))
        except: pass
        log_event(cid, "renegotiated", req.new_deadline)
        _bump_stat(c["owner"], "renegotiated")

    elif req.action == "assign_owner":
        if not req.new_owner: raise HTTPException(400,"new_owner required")
        _update_c(cid, {"owner":req.new_owner,"owner_type":"person","updated_at":now})
        log_event(cid, "assigned", req.new_owner)

    elif req.action == "reassign":
        if not req.new_owner: raise HTTPException(400,"new_owner required")
        _update_c(cid, {"owner":req.new_owner,"status":"open","updated_at":now})
        log_event(cid, "reassigned", req.new_owner)

    elif req.action in ("approve","reject"):
        new_s = "open" if req.action == "approve" else "missed"
        _update_c(cid, {"status":new_s,"updated_at":now})
        log_event(cid, req.action)

    # Sync status back to Notion
    conn = get_db()
    updated = conn.execute("SELECT * FROM commitments WHERE id=?",
                            (cid,)).fetchone()
    conn.close()
    update_commitment_status(
        dict(updated).get("notion_page_id",""),
        req.action, detail=f"Action: {req.action}"
    )
    return {"ok": True}

@app.post("/simulate")
async def simulate(advance_hours: float = 24.0):
    """★ DEMO ENDPOINT — advance agent clock and run watch loop immediately."""
    new_now = advance_clock(advance_hours)
    from scheduler import tick
    tick()
    return {"advanced_hours": advance_hours, "agent_now": new_now}

@app.get("/health")
async def health():
    return {"status":"ok","agent_now":get_agent_now().isoformat(),
            "mock":os.getenv("MOCK_MODE","false")}

@app.get("/commitments")
async def list_commitments(status: str = None, owner: str = None):
    conn = get_db()
    q = ("SELECT c.*,m.title as meeting_title FROM commitments c "
         "JOIN meetings m ON c.meeting_id=m.id WHERE 1=1")
    p = []
    if status: q += " AND c.status=?"; p.append(status)
    if owner:  q += " AND c.owner=?";  p.append(owner)
    rows = conn.execute(q + " ORDER BY c.deadline ASC", p).fetchall()
    conn.close()
    return {"commitments": [dict(r) for r in rows]}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _save_commitment(c: dict, meeting_owner: str,
                     meeting_notion_id: str, meeting_title: str) -> dict:
    if c.get("owner_type") == "ownerless":
        send_ownerless_alert(c, meeting_owner)

    if c.get("owner_type") == "person":
        result = classify(c)
        action = result["action"]

        if action == "renegotiate":
            _update_c(result["target_id"],
                      {"deadline":c.get("deadline",""),
                       "status":"renegotiated",
                       "updated_at":datetime.utcnow().isoformat()})
            log_event(result["target_id"], "renegotiated")
            return {**c,"action_taken":"renegotiated_existing"}

        if action == "merge":
            log_event(result["target_id"], "merged")
            return {**c,"action_taken":"merged_with_existing"}

        if action == "recommit":
            c["warning"] = result.get("warning","")
            send_recommit_warning(c, c["warning"])

    # Overcommitment check
    conn = get_db()
    stat   = conn.execute("SELECT * FROM person_stats WHERE person=?",
                           (c.get("owner",""),)).fetchone()
    open_n = conn.execute("""SELECT COUNT(*) as n FROM commitments
        WHERE owner=? AND status IN ('open','nudged','escalated')""",
        (c.get("owner",""),)).fetchone()["n"]
    conn.close()
    if stat and open_n > stat["avg_completion_per_week"] * 1.5:
        send_overcommit_warning(c["owner"], open_n,
                                stat["avg_completion_per_week"])

    # Create Notion commitment page
    notion_page = create_commitment_page(c, meeting_title)
    if notion_page:
        c["notion_page_id"] = notion_page

    # Insert SQLite
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
        c["id"], c["meeting_id"], c.get("owner","?"),
        c.get("beneficiary",""), c.get("commitment_text",""),
        c.get("normalized_task",""), c.get("explicit_deadline",""),
        c.get("deadline",""), c.get("original_deadline",""),
        c.get("deadline_clue",""), c.get("status","open"),
        c.get("owner_type","person"), c.get("item_type","self_commitment"),
        c.get("assigned_by",""), c.get("confidence",0.9),
        c.get("depends_on_hint",""), 0, c.get("timestamp_sec",0),
        c.get("warning",""), c.get("notion_page_id",""),
        c["created_at"], c["updated_at"]
    ))
    conn.commit(); conn.close()
    log_event(c["id"], "extracted")
    return {**c, "action_taken":"created"}

def _gen_mom(m: dict, commitments: list, agenda: dict) -> str:
    from llm import call
    from prompts import MOM_PROMPT
    try:
        return call(
            system="You write professional meeting minutes.",
            user=MOM_PROMPT.format(
                title=m["title"], date=m["date"],
                attendees=m.get("attendees","[]"),
                transcript=m.get("transcript","")[:3000],
                commitments_json=json.dumps(commitments[:20]),
                agenda_json=json.dumps(agenda.get("slots",[]))
            ),
            temperature=0.3, max_tokens=1500, expect_json=False
        )
    except Exception as e:
        print(f"[MoM] generation failed: {e}")
        return ""

def _gen_pre_brief(attendees: list, context: str = "") -> str:
    from llm import call
    from prompts import CROSS_MEETING_BRIEF_PROMPT

    conn = get_db()
    open_items = conn.execute("""
        SELECT c.*, m.title as meeting_title
        FROM commitments c JOIN meetings m ON c.meeting_id=m.id
        WHERE c.owner IN ({}) AND c.status IN ('open','nudged','escalated','missed')
        ORDER BY c.deadline ASC LIMIT 20
    """.format(",".join("?"*len(attendees))), attendees).fetchall()

    recommits = conn.execute("""
        SELECT owner, normalized_task, COUNT(*) as n
        FROM commitments WHERE owner IN ({})
        GROUP BY owner, normalized_task HAVING n > 1
    """.format(",".join("?"*len(attendees))), attendees).fetchall()
    conn.close()

    flags = [f"{r['owner']} committed to '{r['normalized_task']}' {r['n']} times"
             for r in recommits]
    if context:
        flags.append(f"Pre-meeting context: {context}")

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
    except:
        return ""

def _gen_pattern_report() -> dict:
    from llm import call
    from prompts import PATTERN_REPORT_PROMPT

    conn = get_db()
    stats = conn.execute("SELECT * FROM person_stats ORDER BY missed DESC").fetchall()
    debt  = conn.execute("""
        SELECT m.id,m.title,m.date,
               COUNT(c.id) as total,
               SUM(CASE WHEN c.status='done' THEN 1 ELSE 0 END) as done_n,
               SUM(CASE WHEN c.status='missed' THEN 1 ELSE 0 END) as missed_n
        FROM meetings m LEFT JOIN commitments c ON c.meeting_id=m.id
        GROUP BY m.id ORDER BY m.date DESC
    """).fetchall()
    conn.close()

    stats_list = []
    for s in stats:
        s = dict(s)
        total = s.get("committed",0) or 1
        s["follow_through"] = round(s.get("on_time",0)/total,2)
        s["at_risk"]        = s["follow_through"] < 0.5 and s.get("committed",0) >= 3
        stats_list.append(s)
        upsert_person_page(s)

    debt_list = []
    for d in debt:
        d = dict(d)
        t = d.get("total",0) or 1
        d["rate"]          = round(d.get("done_n",0)/t, 2)
        d["suggest_async"] = d["rate"] < 0.3 and d.get("total",0) >= 3
        debt_list.append(d)

    try:
        summary = call(
            system="You write coaching summaries for team leads.",
            user=PATTERN_REPORT_PROMPT.format(stats_json=json.dumps(stats_list)),
            temperature=0.4, max_tokens=300, expect_json=False
        )
    except:
        summary = "Pattern report generated."

    return {"summary": summary, "stats": stats_list, "debt": debt_list}

def _all_commitments(meeting_id: str) -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM commitments WHERE meeting_id=?",
                        (meeting_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _update_c(cid: str, fields: dict):
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE commitments SET {sets} WHERE id=?",
                 list(fields.values())+[cid])
    conn.commit(); conn.close()

def _bump_stat(person: str, field: str):
    conn = get_db()
    conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?",
                 (person,))
    conn.commit(); conn.close()
```

---

## EXTENSION FILES

### extension/manifest.json

```json
{
  "manifest_version": 3,
  "name": "Meeting Debt Collector",
  "version": "1.0.0",
  "description": "Captures live captions from Google Meet, Zoom, and Teams. Extracts commitments autonomously.",
  "permissions": ["activeTab", "storage", "scripting", "alarms", "tabs"],
  "host_permissions": [
    "https://meet.google.com/*",
    "https://*.zoom.us/*",
    "https://teams.microsoft.com/*",
    "https://teams.live.com/*",
    "http://localhost:8000/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": ["https://meet.google.com/*"],
      "js": ["content_common.js", "content_meet.js"],
      "run_at": "document_idle"
    },
    {
      "matches": ["https://*.zoom.us/wc/*", "https://*.zoom.us/j/*"],
      "js": ["content_common.js", "content_zoom.js"],
      "run_at": "document_idle"
    },
    {
      "matches": ["https://teams.microsoft.com/*", "https://teams.live.com/*"],
      "js": ["content_common.js", "content_teams.js"],
      "run_at": "document_idle"
    }
  ],
  "action": {
    "default_popup": "popup.html",
    "default_icon":  "icon.png"
  }
}
```

### extension/content_common.js  ← SHARED LOGIC

```javascript
// content_common.js
// Shared caption processing logic for all meeting platforms.
// Each platform-specific file sets window.MDC_PLATFORM and window.MDC_SELECTORS,
// then calls MDC.init()

window.MDC = window.MDC || {};

MDC.AGENT_URL   = "http://localhost:8000";
MDC.CHUNK_EVERY = 30000;    // ms
MDC.POLL_MS     = 500;

MDC.state = {
  meetingId:    null,
  isCapturing:  false,
  buffer:       [],
  lastSeen:     "",
  chunkIndex:   0,
  chunkTimer:   null,
  pollTimer:    null,
};

MDC.init = function() {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "START_CAPTURE") {
      MDC.startCapture(msg.meetTitle, msg.meetType, msg.preBrief)
         .then(r => sendResponse(r));
      return true;
    }
    if (msg.type === "STOP_CAPTURE") {
      MDC.stopCapture().then(r => sendResponse(r));
      return true;
    }
    if (msg.type === "GET_STATUS") {
      sendResponse({
        isCapturing:  MDC.state.isCapturing,
        meetingId:    MDC.state.meetingId,
        bufferSize:   MDC.state.buffer.length,
        chunksSent:   MDC.state.chunkIndex,
      });
    }
  });

  window.addEventListener("beforeunload", () => {
    if (MDC.state.isCapturing) MDC.stopCapture();
  });

  console.log(`[MDC] Loaded on ${window.MDC_PLATFORM || "unknown"}`);
};

MDC.startCapture = async function(meetTitle, meetType, preBrief) {
  if (MDC.enableCaptions) MDC.enableCaptions();

  const attendees = MDC.detectAttendees ? MDC.detectAttendees() : [];

  try {
    const resp = await fetch(`${MDC.AGENT_URL}/meetings/start`, {
      method:  "POST",
      headers: {"Content-Type":"application/json"},
      body:    JSON.stringify({
        title:     meetTitle || document.title || "Meeting",
        type:      meetType  || "club_meeting",
        platform:  window.MDC_PLATFORM || "unknown",
        owner:     attendees[0]?.name || "Unknown",
        attendees: attendees,
        pre_brief: preBrief || ""
      })
    });
    const data = await resp.json();
    MDC.state.meetingId = data.meeting_id;
  } catch(e) {
    console.error("[MDC] Failed to start meeting:", e);
    return {ok: false, error: e.message};
  }

  MDC.state.isCapturing = true;
  MDC.state.buffer      = [];
  MDC.state.lastSeen    = "";
  MDC.state.chunkIndex  = 0;

  MDC.state.pollTimer  = setInterval(MDC.poll, MDC.POLL_MS);
  MDC.state.chunkTimer = setInterval(MDC.sendChunk, MDC.CHUNK_EVERY);

  chrome.runtime.sendMessage({
    type: "CAPTURE_STARTED",
    meetingId: MDC.state.meetingId,
    platform:  window.MDC_PLATFORM
  });

  return {ok: true, meetingId: MDC.state.meetingId};
};

MDC.stopCapture = async function() {
  MDC.state.isCapturing = false;
  clearInterval(MDC.state.pollTimer);
  clearInterval(MDC.state.chunkTimer);

  await MDC.sendChunk();  // flush remaining buffer

  if (MDC.state.meetingId) {
    try {
      await fetch(`${MDC.AGENT_URL}/meetings/${MDC.state.meetingId}/end`,
                  {method:"POST"});
    } catch(e) {
      console.error("[MDC] Finalize failed:", e);
    }
  }

  chrome.runtime.sendMessage({type: "CAPTURE_STOPPED"});
  return {ok: true};
};

MDC.poll = function() {
  if (!MDC.state.isCapturing) return;

  let text    = "";
  let speaker = "Unknown";

  // Try each selector defined by the platform content script
  for (const sel of (window.MDC_SELECTORS?.caption || [])) {
    const el = document.querySelector(sel);
    if (el?.textContent?.trim()) { text = el.textContent.trim(); break; }
  }
  for (const sel of (window.MDC_SELECTORS?.speaker || [])) {
    const el = document.querySelector(sel);
    if (el?.textContent?.trim()) { speaker = el.textContent.trim(); break; }
  }

  if (!text || text === MDC.state.lastSeen) return;
  MDC.state.lastSeen = text;

  const entry = {speaker, text, ts: Date.now()};
  MDC.state.buffer.push(entry);

  chrome.runtime.sendMessage({type:"NEW_CAPTION", entry,
                               meetingId: MDC.state.meetingId});
};

MDC.sendChunk = async function() {
  if (!MDC.state.buffer.length || !MDC.state.meetingId) return;

  const chunk = MDC.state.buffer
    .map(e => `[${new Date(e.ts).toLocaleTimeString()}] ${e.speaker}: ${e.text}`)
    .join("\n");
  MDC.state.buffer = [];

  try {
    const resp = await fetch(
      `${MDC.AGENT_URL}/meetings/${MDC.state.meetingId}/chunk`,
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({chunk, chunk_index: MDC.state.chunkIndex++})}
    );
    const data = await resp.json();
    chrome.runtime.sendMessage({type:"CHUNK_SENT", result: data});
  } catch(e) {
    console.error("[MDC] Chunk send failed:", e);
  }
};
```

### extension/content_meet.js

```javascript
// content_meet.js — Google Meet caption selectors
window.MDC_PLATFORM = "google_meet";

window.MDC_SELECTORS = {
  caption: [
    '[data-message-text]',
    '[jsname="tgaKEf"] span',
    '.a4cQT',
    '[aria-live="polite"] span',
    '[jsname="YSg7Ld"]'
  ],
  speaker: [
    '[data-sender-name]',
    '.zs7s8d',
    '[jsname="r4nke"]',
    '[data-self-name]'
  ]
};

MDC.enableCaptions = function() {
  const btn = document.querySelector(
    '[aria-label="Turn on captions"],[data-tooltip="Turn on captions"]'
  );
  if (btn && btn.getAttribute("aria-pressed") !== "true") {
    btn.click();
    console.log("[MDC] Auto-enabled Meet captions");
  }
};

MDC.detectAttendees = function() {
  const names = new Set();
  document.querySelectorAll('[data-participant-id] [data-tooltip]')
    .forEach(el => { if(el.textContent.trim()) names.add(el.textContent.trim()); });
  document.querySelectorAll('.cS7aqe, [jsname="M8Ambd"]')
    .forEach(el => { if(el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({name: n}))
    : [{name:"Alice"},{name:"Bob"},{name:"Rohith"},{name:"Priya"}];
};

MDC.init();
```

### extension/content_zoom.js

```javascript
// content_zoom.js — Zoom caption selectors
window.MDC_PLATFORM = "zoom";

window.MDC_SELECTORS = {
  caption: [
    '.caption-line',
    '[class*="caption-line"]',
    '.live-transcription-subtitle',
    '[aria-label*="caption"] span',
    '.zmwebsdk-MuiTypography-root'
  ],
  speaker: [
    '.speaker-name',
    '[class*="speaker-name"]',
    '.live-transcription-speaker-name'
  ]
};

MDC.enableCaptions = function() {
  // Zoom: look for CC button in toolbar
  const ccBtn = document.querySelector(
    '[aria-label="Show Captions"],[aria-label*="Caption"],[id*="caption"]'
  );
  if (ccBtn) { ccBtn.click(); console.log("[MDC] Auto-enabled Zoom captions"); }
};

MDC.detectAttendees = function() {
  const names = new Set();
  document.querySelectorAll('[class*="participant-item"] [class*="display-name"]')
    .forEach(el => { if(el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({name: n}))
    : [{name:"Participant 1"},{name:"Participant 2"}];
};

MDC.init();
```

### extension/content_teams.js

```javascript
// content_teams.js — Microsoft Teams caption selectors
window.MDC_PLATFORM = "microsoft_teams";

window.MDC_SELECTORS = {
  caption: [
    '[data-tid="closed-captions-renderer"] span',
    '.ts-captions-container span',
    '[class*="caption"] span',
    '[aria-label*="caption"]',
    '.fui-Caption1'
  ],
  speaker: [
    '[data-tid="closed-captions-renderer-speaker"]',
    '.ts-captions-speaker',
    '[class*="captionSpeaker"]'
  ]
};

MDC.enableCaptions = function() {
  const ccBtn = document.querySelector(
    '[data-tid="toggle-captions"],[aria-label*="captions"],[aria-label*="Captions"]'
  );
  if (ccBtn) { ccBtn.click(); console.log("[MDC] Auto-enabled Teams captions"); }
};

MDC.detectAttendees = function() {
  const names = new Set();
  document.querySelectorAll('[data-tid*="participant"] [class*="name"]')
    .forEach(el => { if(el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({name: n}))
    : [{name:"Participant 1"},{name:"Participant 2"}];
};

MDC.init();
```

### extension/background.js

```javascript
// background.js — service worker
let state = {
  isCapturing:  false,
  meetingId:    null,
  platform:     null,
  chunksSent:   0,
  commitments:  0,
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "CAPTURE_STARTED") {
    state.isCapturing = true;
    state.meetingId   = msg.meetingId;
    state.platform    = msg.platform;
    state.chunksSent  = 0;
    state.commitments = 0;
    chrome.action.setBadgeText({text:"●"});
    chrome.action.setBadgeBackgroundColor({color:"#1D9E75"});
  }

  if (msg.type === "CAPTURE_STOPPED") {
    state.isCapturing = false;
    chrome.action.setBadgeText({text:""});
  }

  if (msg.type === "CHUNK_SENT") {
    state.chunksSent++;
    state.commitments += msg.result?.commitments_this_chunk || 0;
    chrome.action.setBadgeText({text: String(state.commitments) || "●"});
  }

  if (msg.type === "NEW_CAPTION") {
    chrome.storage.session.get("captions", d => {
      const list = (d.captions || []).slice(-10);
      list.push(msg.entry);
      chrome.storage.session.set({captions: list});
    });
  }

  if (msg.type === "GET_STATE") {
    sendResponse(state);
  }
});
```

### extension/popup.html

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div class="header">
    <span class="logo">🎯</span>
    <h1>Meeting Debt Collector</h1>
  </div>

  <div id="badge-row">
    <span id="badge" class="badge off">Not capturing</span>
    <span id="platform-badge" class="platform-badge" style="display:none"></span>
  </div>

  <!-- PRE-MEETING SETUP -->
  <div id="setup-section">
    <label>Meeting title</label>
    <input type="text" id="meetTitle" placeholder="Sprint Review · Aug 1">

    <label>Meeting type</label>
    <select id="meetType">
      <option value="sprint_review">Sprint Review</option>
      <option value="project_kickoff">Project Kickoff</option>
      <option value="event_planning">Event Planning</option>
      <option value="club_meeting" selected>Club Meeting / General</option>
    </select>

    <label>Pre-meeting context (optional)</label>
    <textarea id="preBrief" rows="3"
      placeholder="E.g. Last week Alice missed the API deadline. Today we need to finalize the demo plan."></textarea>

    <button class="btn-start" id="startBtn">▶ Start Capturing</button>
  </div>

  <!-- LIVE CAPTURE VIEW -->
  <div id="live-section" style="display:none">
    <div class="stats-row">
      <div class="stat"><span id="chunkCount">0</span><small>chunks</small></div>
      <div class="stat"><span id="commitCount">0</span><small>commitments</small></div>
    </div>
    <div class="caption-feed" id="captionFeed">
      <div class="waiting">Listening for captions...</div>
    </div>
    <button class="btn-stop" id="stopBtn">■ Stop & Save to Notion</button>
  </div>

  <div id="status-msg"></div>
  <script src="popup.js"></script>
</body>
</html>
```

### extension/popup.css

```css
body {
  width: 300px; min-height: 200px;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px; padding: 12px; margin: 0;
  background: #fff; color: #1a1a1a;
}
.header { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.logo { font-size:20px; }
h1 { font-size:14px; font-weight:600; margin:0; }
#badge-row { display:flex; gap:6px; align-items:center; margin-bottom:10px; }
.badge { padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600; }
.badge.off { background:#f1efe8; color:#5f5e5a; }
.badge.on  { background:#d4f4e6; color:#0f6e56; }
.platform-badge { background:#e6f1fb; color:#185fa5;
                   padding:3px 8px; border-radius:12px; font-size:11px; }
label { display:block; font-size:11px; color:#666; margin:6px 0 2px; }
input, select, textarea {
  width:100%; box-sizing:border-box;
  border:1px solid #ddd; border-radius:6px;
  padding:6px 8px; font-size:12px; margin-bottom:6px;
  font-family:inherit;
}
textarea { resize:vertical; }
button { width:100%; padding:9px; border:none; border-radius:6px;
         font-size:13px; font-weight:600; cursor:pointer; margin-top:4px; }
.btn-start { background:#1D9E75; color:#fff; }
.btn-start:hover { background:#0f6e56; }
.btn-stop  { background:#e24b4a; color:#fff; }
.btn-stop:hover { background:#a32d2d; }
.stats-row { display:flex; gap:12px; margin-bottom:8px; }
.stat { flex:1; text-align:center; background:#f8f8f6;
        border-radius:8px; padding:8px 4px; }
.stat span { display:block; font-size:20px; font-weight:700; color:#1D9E75; }
.stat small { font-size:10px; color:#888; }
.caption-feed {
  background:#f8f8f6; border-radius:8px; padding:8px;
  max-height:120px; overflow-y:auto; margin-bottom:8px;
  font-size:11px; color:#444; line-height:1.4;
}
.caption-line { margin-bottom:4px; }
.speaker { font-weight:700; color:#1D9E75; }
.waiting { color:#aaa; font-style:italic; }
#status-msg { font-size:11px; color:#888; margin-top:6px; min-height:16px; }
```

### extension/popup.js

```javascript
let isCapturing = false;

async function getMeetTab() {
  const patterns = [
    "https://meet.google.com/*",
    "https://*.zoom.us/wc/*",
    "https://*.zoom.us/j/*",
    "https://teams.microsoft.com/*",
    "https://teams.live.com/*"
  ];
  for (const p of patterns) {
    const tabs = await chrome.tabs.query({url: p});
    if (tabs.length) return tabs[0];
  }
  return null;
}

async function sendToContent(msg) {
  const tab = await getMeetTab();
  if (!tab) {
    setStatus("No active meeting tab found. Join a call first.");
    return null;
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, msg);
  } catch(e) {
    setStatus("Cannot reach content script. Refresh the meeting tab.");
    return null;
  }
}

document.getElementById("startBtn").addEventListener("click", async () => {
  const meetTitle = document.getElementById("meetTitle").value.trim();
  const meetType  = document.getElementById("meetType").value;
  const preBrief  = document.getElementById("preBrief").value.trim();

  setStatus("Starting...");
  const result = await sendToContent({
    type: "START_CAPTURE", meetTitle, meetType, preBrief
  });

  if (result?.ok) {
    isCapturing = true;
    updateUI();
    setStatus("Live! Notion page created.");
  } else {
    setStatus("Failed to start. Is the agent running? (localhost:8000)");
  }
});

document.getElementById("stopBtn").addEventListener("click", async () => {
  setStatus("Saving to Notion...");
  const result = await sendToContent({type: "STOP_CAPTURE"});
  if (result?.ok) {
    isCapturing = false;
    updateUI();
    setStatus("Saved! Check Notion for the report.");
  }
});

function updateUI() {
  document.getElementById("badge").textContent = isCapturing ? "● Capturing live" : "Not capturing";
  document.getElementById("badge").className   = `badge ${isCapturing?"on":"off"}`;
  document.getElementById("setup-section").style.display = isCapturing ? "none" : "block";
  document.getElementById("live-section").style.display  = isCapturing ? "block" : "none";
}

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

async function pollState() {
  try {
    const state = await chrome.runtime.sendMessage({type:"GET_STATE"});
    if (state?.isCapturing !== undefined) {
      isCapturing = state.isCapturing;
      updateUI();
    }
    if (state) {
      document.getElementById("chunkCount").textContent  = state.chunksSent  || 0;
      document.getElementById("commitCount").textContent = state.commitments  || 0;
      const pb = document.getElementById("platform-badge");
      if (state.platform) {
        pb.textContent = state.platform.replace("_"," ");
        pb.style.display = "inline";
      }
    }

    // Refresh caption feed
    const d = await chrome.storage.session.get("captions");
    const captions = (d.captions || []).slice(-5).reverse();
    if (captions.length) {
      document.getElementById("captionFeed").innerHTML = captions
        .map(c => `<div class="caption-line">
                     <span class="speaker">${c.speaker}:</span> ${c.text}
                   </div>`)
        .join("");
    }
  } catch(e) {}
}

// Init
(async () => {
  const state = await chrome.runtime.sendMessage({type:"GET_STATE"}).catch(()=>null);
  if (state?.isCapturing) { isCapturing = true; updateUI(); }
  setInterval(pollState, 1000);
})();
```

---

## AGENDA TEMPLATES (copy exactly into agent/templates/)

### sprint_review.json
```json
{
  "type": "sprint_review",
  "slots": [
    {"id":"blockers",     "label":"Blockers discussed",          "required":true},
    {"id":"demos",        "label":"Work demoed",                 "required":false},
    {"id":"next_scope",   "label":"Next sprint scope agreed",    "required":true},
    {"id":"owners",       "label":"Every task has a named owner","required":true},
    {"id":"testing",      "label":"Testing plan mentioned",      "required":true},
    {"id":"retro",        "label":"What went wrong discussed",   "required":false}
  ]
}
```

### event_planning.json
```json
{
  "type": "event_planning",
  "slots": [
    {"id":"venue",       "label":"Venue confirmed",              "required":true},
    {"id":"budget",      "label":"Budget discussed",             "required":true},
    {"id":"permissions", "label":"Permissions assigned",         "required":true},
    {"id":"publicity",   "label":"Publicity plan mentioned",     "required":false},
    {"id":"volunteers",  "label":"Volunteer roles assigned",     "required":true},
    {"id":"owners",      "label":"Every task has a named owner", "required":true}
  ]
}
```

### project_kickoff.json
```json
{
  "type": "project_kickoff",
  "slots": [
    {"id":"goals",     "label":"Goals defined",                 "required":true},
    {"id":"roles",     "label":"Roles assigned",                "required":true},
    {"id":"timeline",  "label":"Timeline set",                  "required":true},
    {"id":"risks",     "label":"Risks identified",              "required":false},
    {"id":"milestone", "label":"First milestone named + owner", "required":true},
    {"id":"owners",    "label":"Every task has a named owner",  "required":true}
  ]
}
```

### club_meeting.json
```json
{
  "type": "club_meeting",
  "slots": [
    {"id":"attendance",   "label":"Attendance noted",            "required":false},
    {"id":"next_event",   "label":"Next event planned",          "required":true},
    {"id":"action_items", "label":"Action items assigned",       "required":true},
    {"id":"owners",       "label":"Every task has a named owner","required":true}
  ]
}
```

---

## HOW TO INSTALL AND RUN

### 1. Agent (backend)
```bash
cd agent
pip install -r ../requirements.txt
cp ../.env.example ../.env
# Fill in: FEATHERLESS_API_KEY (already have it), NOTION_TOKEN, NOTION_PARENT_PAGE_ID
# Optionally: TWILIO_*, SLACK_WEBHOOK_URL

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# On first run, Notion databases are created automatically.
```

### 2. Chrome extension
```
1. Open Chrome → chrome://extensions/
2. Enable "Developer mode" (toggle, top right)
3. Click "Load unpacked"
4. Select the extension/ folder
5. Extension icon appears in toolbar
```

### 3. Use it
```
1. Join a Google Meet / Zoom / Teams call
2. Click the extension icon
3. Enter meeting title + type
4. Optionally type pre-meeting context
5. Click "▶ Start Capturing"
   → Agent creates meeting in Notion automatically
   → Captions auto-enabled on Meet
6. Speak normally
   → Every 30s: chunk POSTed → commitments extracted → Notion updated live
   → Ownerless commitments → Slack alert fires immediately
   → Agenda checklist fills in as topics are covered
7. End of meeting: Click "■ Stop & Save to Notion"
   → MoM written to Notion meeting page
   → Pattern report page created in Notion
   → Watch loop continues ticking for all deadlines
8. As deadlines approach: WhatsApp buzzes / Slack pings automatically
```

### 4. Demo simulation
```bash
# Advance clock (skips real waiting)
curl -X POST "http://localhost:8000/simulate?advance_hours=24"

# Check all open commitments
curl http://localhost:8000/commitments?status=open

# Mark done (simulate WhatsApp reply)
curl -X POST http://localhost:8000/commitments/COMMITMENT_ID/action \
  -H "Content-Type: application/json" -d '{"action":"done"}'
```

---

## NOTION SETUP (5 minutes)

```
1. Go to notion.so/my-integrations
2. New integration → name it "MeetingDebtCollector" → Submit
3. Copy the Internal Integration Secret → NOTION_TOKEN in .env

4. Create a blank page in Notion (this is your parent page)
5. Click ••• → Connections → Add your integration
6. Copy the page ID from the URL:
   notion.so/YourWorkspace/[THIS-32-CHAR-ID]?...
   → NOTION_PARENT_PAGE_ID in .env

7. Run the agent — it creates all 4 databases automatically on startup
```

---

## WHAT GETS WRITTEN TO NOTION (complete list)

```
On meeting start:
  → New page in Meetings database (title, type, platform, date, owner)
  → Pre-brief callout block added to meeting page

Every 30s (per chunk):
  → New page per commitment in Commitments database
      (task, owner, deadline, status, verbatim quote, confidence, depends-on)
  → Verbatim quote block + timestamp added to commitment page
  → Meeting page commitment count updated

On wrapup cue detected:
  → Slack alert (missed agenda items)

On meeting end:
  → Full MoM appended to meeting page as formatted blocks
  → Agenda coverage table appended to meeting page
  → Each agenda slot logged to Agenda database
  → Meeting status → "finalized"
  → New Pattern Report page created under parent page
      (LLM coaching summary, per-person stats, meeting debt scores)
  → People database upserted (one page per person, stats updated)

On nudge (T-24h):
  → WhatsApp / Slack message sent
  → Commitment page: status → "nudged", nudge logged as callout block

On escalation (T-6h):
  → Slack message to meeting owner
  → Commitment page: status → "escalated"

On miss:
  → Commitment page: status → "missed"
  → Cascade: downstream commitments shifted + each notified via Slack
  → Reassignment suggestion generated if owner overloaded

On done:
  → Commitment page: status → "done"
  → Beneficiary notification sent
  → Person stats: on_time +1
  → People database page updated
```
