# Meeting Debt Collector — Complete Build Specification
# Hand this file directly to Claude Code or any AI coding assistant.
# Every section is implementation-ready. Follow top to bottom.

---

## 0. API KEYS — WHAT YOU NEED, ALL FREE

### Keys you must have before building anything:

```
GROQ_API_KEY=           # Already created. Used for ALL LLM calls.
                        # Model: llama-3.3-70b-versatile
                        # Free: 30 req/min, 14,400/day — more than enough.

NOTION_TOKEN=           # Free. notion.so/my-integrations → New integration
NOTION_DB_ID=           # The 32-char ID from your Notion database URL

SLACK_WEBHOOK_URL=      # Free. api.slack.com/apps → Incoming Webhooks
                        # This is for OUTBOUND nudges only (one-way push)
                        # No bot token needed, just the webhook URL

TWILIO_ACCOUNT_SID=     # Free trial at twilio.com. Gives ~$15 credit.
TWILIO_AUTH_TOKEN=       # Used for WhatsApp sandbox nudges on demo day
TWILIO_WHATSAPP_FROM=   # Format: whatsapp:+14155238886 (Twilio sandbox number)
TWILIO_WHATSAPP_TO=     # Your phone: whatsapp:+91XXXXXXXXXX

GOOGLE_CALENDAR_CREDS=  # Path to credentials.json from Google Cloud Console
                        # console.cloud.google.com → new project →
                        # enable "Google Calendar API" →
                        # Create credentials → OAuth 2.0 → Desktop App →
                        # Download credentials.json → put in /backend/

MOCK_MODE=false         # Set to "true" to bypass ALL external APIs.
                        # Returns hardcoded realistic responses.
                        # Use this if any API is slow/down on demo day.
```

### Steps to get each key:

**Groq** (already done): console.groq.com → API Keys

**Notion**:
1. notion.so/my-integrations → New integration → name it "MeetingDebtCollector" → Submit
2. Copy Internal Integration Secret → NOTION_TOKEN
3. In Notion, create a database (full-page table) with these exact columns:
   - Owner (Title type)
   - Commitment (Text type)
   - Deadline (Date type)
   - Status (Select: open, nudged, escalated, done, missed, renegotiated)
   - Source Meeting (Text type)
   - Confidence (Select: high, medium, low)
   - Depends On (Text type)
4. Open that database → top-right ••• → Connections → add your integration
5. Copy the 32-char ID from the URL → NOTION_DB_ID

**Slack**:
1. api.slack.com/apps → Create New App → From scratch
2. Name: MeetingDebtCollector, pick your workspace
3. Incoming Webhooks → Activate → Add to Workspace → pick #general or #demo
4. Copy webhook URL → SLACK_WEBHOOK_URL

**Twilio WhatsApp Sandbox**:
1. twilio.com → sign up → verify phone
2. Console → Messaging → Try it out → Send a WhatsApp message
3. Follow sandbox setup (send "join <word>" from your phone to the sandbox number)
4. TWILIO_WHATSAPP_FROM = whatsapp:+14155238886
5. TWILIO_WHATSAPP_TO = whatsapp:+91XXXXXXXXXX (your number)

**Google Calendar**:
1. console.cloud.google.com → new project → enable "Google Calendar API"
2. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID → Desktop App
3. Download credentials.json → place in backend/
4. First run of calendar.py opens browser consent once, then saves token.json automatically

---

## 1. FOLDER STRUCTURE

Create this exact structure before writing any code:

```
meeting-debt-collector/
├── README.md
├── .env                          ← gitignored, your real keys
├── .env.example                  ← committed, placeholder keys
├── .gitignore
├── requirements.txt
│
├── backend/
│   ├── main.py                   ← FastAPI app, all routes
│   ├── models.py                 ← SQLite schema + DB helpers
│   ├── extractor.py              ← LLM #1: commitment extraction
│   ├── resolver.py               ← LLM #2: deadline resolution
│   ├── nudger.py                 ← LLM #3: message generation + delivery
│   ├── scheduler.py              ← watch loop, injectable clock
│   ├── similarity.py             ← embedding + cosine sim engine
│   ├── agenda.py                 ← live agenda coverage agent
│   ├── calendar_agent.py         ← Google Calendar integration
│   ├── notion_mirror.py          ← Notion API mirror (fire-and-forget)
│   ├── mock_responses.py         ← MOCK_MODE hardcoded responses
│   ├── prompts.py                ← ALL LLM prompts as named constants
│   ├── credentials.json          ← Google OAuth (gitignored)
│   └── templates/
│       ├── sprint_review.json
│       ├── event_planning.json
│       ├── project_kickoff.json
│       └── club_meeting.json
│
├── frontend/
│   ├── index.html                ← single HTML file, no build step needed
│   └── app.js                    ← vanilla JS, polls backend every 2s
│
├── synthetic_data/
│   ├── transcript_1_clean.txt
│   ├── transcript_2_messy.txt
│   └── transcript_3_followup.txt
│
└── docs/
    ├── architecture.png          ← screenshot of the diagram below
    └── demo_script.md            ← the 4-min demo walkthrough

```

---

## 2. REQUIREMENTS.TXT

```
fastapi==0.111.0
uvicorn==0.29.0
python-dotenv==1.0.1
groq==0.9.0
requests==2.31.0
twilio==9.0.5
notion-client==2.2.2
google-auth==2.29.0
google-auth-oauthlib==1.2.0
google-api-python-client==2.127.0
apscheduler==3.10.4
numpy==1.26.4
aiofiles==23.2.1
python-multipart==0.0.9
```

---

## 3. .ENV.EXAMPLE (commit this, not .env)

```
# LLM
GROQ_API_KEY=your_groq_api_key_here

# Task structuring
NOTION_TOKEN=your_notion_integration_token_here
NOTION_DB_ID=your_notion_database_id_here

# Nudge delivery
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+91XXXXXXXXXX

# Calendar (path to downloaded credentials.json)
GOOGLE_CALENDAR_CREDS=backend/credentials.json

# Demo control
MOCK_MODE=false
```

---

## 4. GITIGNORE

```
.env
backend/credentials.json
backend/token.json
__pycache__/
*.pyc
*.db
.DS_Store
```

---

## 5. MODELS.PY — SQLITE SCHEMA

```python
import sqlite3
import json
from datetime import datetime

DB_PATH = "meeting_debt.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        date TEXT NOT NULL,
        owner TEXT NOT NULL,
        attendees TEXT NOT NULL,       -- JSON array of {name, email, slack_handle}
        transcript TEXT DEFAULT '',
        audio_path TEXT DEFAULT '',
        status TEXT DEFAULT 'active',  -- active | finalized | closed
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitments (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        owner TEXT NOT NULL,
        beneficiary TEXT DEFAULT '',
        commitment_text TEXT NOT NULL,     -- verbatim quote from transcript
        normalized_task TEXT NOT NULL,     -- cleaned-up action description
        embedding TEXT DEFAULT '',         -- JSON float array for similarity
        explicit_deadline TEXT DEFAULT '', -- e.g. "Thursday"
        deadline TEXT DEFAULT '',          -- resolved ISO timestamp
        original_deadline TEXT DEFAULT '', -- set once, never overwritten
        deadline_clue TEXT DEFAULT '',     -- e.g. "before the client call"
        status TEXT DEFAULT 'open',
        -- open | nudged | escalated | done | renegotiated | reassigned | missed
        -- | needs_clarification | review
        owner_type TEXT DEFAULT 'person',  -- person | ownerless | vague_intention
        item_type TEXT DEFAULT 'self_commitment',
        -- self_commitment | assignment | meeting_request
        assigned_by TEXT DEFAULT '',
        confidence REAL DEFAULT 0.9,
        depends_on TEXT DEFAULT '',        -- commitment ID this blocks on
        nudge_count INTEGER DEFAULT 0,
        timestamp_sec INTEGER DEFAULT 0,   -- position in transcript audio
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (meeting_id) REFERENCES meetings(id)
    );

    CREATE TABLE IF NOT EXISTS commitment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_id TEXT NOT NULL,
        event TEXT NOT NULL,               -- extracted|nudged|escalated|done|missed|renegotiated|reassigned
        detail TEXT DEFAULT '',
        at TEXT NOT NULL,
        FOREIGN KEY (commitment_id) REFERENCES commitments(id)
    );

    CREATE TABLE IF NOT EXISTS agenda_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id TEXT NOT NULL,
        slot_id TEXT NOT NULL,
        label TEXT NOT NULL,
        required INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',     -- pending | covered | missed
        evidence_quote TEXT DEFAULT '',
        covered_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS person_stats (
        person TEXT PRIMARY KEY,
        email TEXT DEFAULT '',
        slack_handle TEXT DEFAULT '',
        committed INTEGER DEFAULT 0,
        on_time INTEGER DEFAULT 0,
        renegotiated INTEGER DEFAULT 0,
        missed INTEGER DEFAULT 0,
        avg_completion_per_week REAL DEFAULT 2.0
    );

    CREATE TABLE IF NOT EXISTS agent_clock (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        simulated_now TEXT NOT NULL
    );
    """)

    # Seed agent clock with real current time
    now = datetime.utcnow().isoformat()
    c.execute("""
        INSERT OR IGNORE INTO agent_clock (id, simulated_now) VALUES (1, ?)
    """, (now,))

    # Seed person_stats with realistic demo history
    demo_people = [
        ("Alice", "alice@team.com", "@alice", 8, 6, 1, 1, 3.0),
        ("Bob", "bob@team.com", "@bob", 6, 3, 1, 2, 1.5),
        ("Rohith", "rohith@team.com", "@rohith", 10, 4, 2, 4, 2.0),
        ("Priya", "priya@team.com", "@priya", 7, 7, 0, 0, 3.5),
    ]
    c.executemany("""
        INSERT OR IGNORE INTO person_stats
        (person, email, slack_handle, committed, on_time, renegotiated, missed, avg_completion_per_week)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, demo_people)

    conn.commit()
    conn.close()

def get_agent_now():
    conn = get_db()
    row = conn.execute("SELECT simulated_now FROM agent_clock WHERE id=1").fetchone()
    conn.close()
    from datetime import datetime
    return datetime.fromisoformat(row["simulated_now"])

def advance_agent_clock(hours: float):
    from datetime import timedelta
    now = get_agent_now()
    new_now = (now + timedelta(hours=hours)).isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=? WHERE id=1", (new_now,))
    conn.commit()
    conn.close()
    return new_now
```

---

## 6. PROMPTS.PY — ALL LLM PROMPTS AS NAMED CONSTANTS

```python
# Every prompt is a named constant. Never bury prompts inline in business logic.

EXTRACTION_PROMPT = """
You are an autonomous commitment-extraction agent. Analyze the meeting transcript
and extract ONLY genuine commitments — not vague intentions.

Return a JSON array. Each item must have ALL these fields:

{
  "speaker": "exact name as spoken",
  "commitment_text": "verbatim quote from transcript",
  "normalized_task": "clean action description, 5-10 words",
  "explicit_deadline": "exact deadline phrase if stated, else null",
  "deadline_clue": "contextual hint if no explicit date, else null",
  "depends_on_hint": "phrase showing dependency on another person's task, else null",
  "beneficiary": "person waiting on this, else null",
  "owner_type": "person | ownerless | vague_intention",
  "item_type": "self_commitment | assignment | meeting_request",
  "assigned_by": "speaker name if item_type=assignment, else null",
  "confidence": 0.0 to 1.0,
  "timestamp_sec": integer seconds into transcript where this appears
}

CLASSIFICATION RULES — follow exactly:

owner_type:
- "person" → one named person takes clear responsibility
- "ownerless" → phrased as "we should", "someone needs to", "let's make sure",
  "the team will" — responsibility is diffuse
- "vague_intention" → no real deadline, no ownership, general aspiration
  Examples: "we should look into caching", "it'd be great to refactor this"
  SKIP these — do NOT include them in output

item_type:
- "self_commitment" → person commits for themselves ("I'll do X")
- "assignment" → speaker assigns to someone else ("Priya, can you review X?")
  → owner = the assignee, assigned_by = the speaker
- "meeting_request" → someone proposes a future meeting
  ("Let's grab 15 min Thursday to discuss deployment")

FEW-SHOT EXAMPLES:

Transcript line: "I'll finish the API integration by Thursday"
→ owner_type: "person", item_type: "self_commitment", confidence: 0.95

Transcript line: "we should probably think about caching at some point"
→ owner_type: "vague_intention" — SKIP, do not include

Transcript line: "we'll handle the deployment"
→ owner_type: "ownerless", item_type: "self_commitment"

Transcript line: "once Alice finishes the API, I'll do the integration"
→ depends_on_hint: "once Alice finishes the API"

Transcript line: "Priya, can you review the contract by Friday?"
→ owner_type: "person", item_type: "assignment", owner: "Priya",
   assigned_by: "[speaker name]"

Transcript line: "let's grab 15 minutes Thursday to sort out deployment"
→ item_type: "meeting_request", explicit_deadline: "Thursday"

Return ONLY valid JSON array. No markdown, no explanation, no preamble.
Attendees in this meeting: {attendees}
"""

RESOLUTION_PROMPT = """
You are a deadline resolution agent. Convert vague or implicit deadline references
into specific ISO 8601 timestamps.

Current date and time: {current_datetime}
Calendar context (upcoming events): {calendar_context}

For each commitment, resolve the deadline:
- Explicit date phrases: convert to nearest upcoming occurrence
  ("Thursday" → next Thursday if today is Monday)
- Implicit clues: resolve against calendar events
  ("before the client call" → look in calendar, find "Client Call" event,
   set deadline to 1 hour before)
- "end of week" → Friday 6 PM
- "end of day" → today 6 PM
- "ASAP" or "soon" → now + 24 hours, confidence penalty: subtract 0.2
- Unresolvable → return null, set needs_clarification: true

Input commitment list:
{commitments_json}

Return the SAME array with these fields added or updated:
- "deadline": ISO 8601 string or null
- "needs_clarification": true | false

Return ONLY valid JSON array. No markdown.
"""

NUDGE_GENERATION_PROMPT = """
You are writing a nudge message from a colleague to {owner_name}.
Write in a warm, human tone — like a helpful teammate, not a system alert.

Facts:
- Their exact words from the meeting: "{commitment_text}"
- Meeting name: {meeting_title}
- Meeting date: {meeting_date}
- Deadline: {deadline}
- Hours until deadline: {hours_until}

Rules:
- Quote their own words back to them naturally
- Keep it under 80 words
- Do NOT start with "Reminder:" or "ALERT:"
- End with one concrete suggested action they can take right now
- Sound like a person, not a bot

Return only the message text. No quotes around it. No preamble.
"""

AGENDA_SLOT_MATCHING_PROMPT = """
You are checking whether a meeting transcript chunk covers specific agenda items.

Meeting type: {meeting_type}
Agenda slots to check:
{slots_json}

Transcript chunk (last 30 seconds):
{transcript_chunk}

For each slot, determine if this chunk covers it:
- "covered": clear evidence in this chunk
- "pending": not yet addressed
- "partial": mentioned but not resolved

Return JSON array:
[
  {
    "slot_id": "blockers",
    "status": "covered | pending | partial",
    "evidence_quote": "exact phrase from chunk that covers it, or null"
  }
]

Return ONLY valid JSON. No markdown.
"""

PATTERN_REPORT_PROMPT = """
Generate a private, constructive coaching summary for a team lead.
Data is per-person follow-through rates from the past meetings.

Stats:
{stats_json}

Rules:
- 2-3 sentences maximum
- Frame as coaching opportunity, never blame
- Highlight the person most at risk of overcommitment
- Suggest one concrete structural fix (redistribute, smaller commitments, async)
- Do not use the word "failed" or "missed"

Return only the summary text.
"""

REASSIGNMENT_SUGGESTION_PROMPT = """
Someone on the team is overloaded. Suggest a specific reassignment.

Overloaded person: {overloaded_person}
Their open commitments this week: {open_commitments}
Their historical completion rate: {completion_rate} per week

Available team members with capacity:
{available_members}

Task to potentially reassign: {task_to_reassign}

Write a 1-sentence suggestion for the team lead. Name the specific person
to reassign to and briefly explain why they're a good fit (skills or capacity).
Be concrete. Return only the suggestion text.
"""

CROSS_MEETING_SUMMARY_PROMPT = """
Generate a "since we last spoke" briefing for the start of a new meeting.

New meeting attendees: {attendees}
Open commitments relevant to these attendees (from past meetings):
{open_commitments_json}

Flags to highlight:
{flags_json}

Write a concise briefing (max 5 bullet points) the meeting chair can read
aloud at the start. Focus on:
1. What was promised last time that's still open
2. What's at risk or overdue
3. Anything promised twice without being closed

Return only the bullet points, starting each with "•".
"""

MOM_GENERATION_PROMPT = """
Generate clean meeting minutes from this transcript and commitment list.

Meeting: {meeting_title}
Date: {meeting_date}
Attendees: {attendees}
Transcript: {transcript}

Commitments extracted:
{commitments_json}

Format the minutes as:
## Summary
[2-3 sentence overview of what was discussed]

## Key Decisions
[bullet points of decisions made]

## Commitments
| Owner | Task | Deadline | Status |
[table rows from commitments]

## Follow-up Required
[anything flagged ownerless or needs_clarification]

Keep it professional and concise.
"""
```

---

## 7. EXTRACTOR.PY

```python
import os
import json
import uuid
from datetime import datetime
from groq import Groq
from prompts import EXTRACTION_PROMPT
from mock_responses import MOCK_EXTRACTION

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

def extract_commitments(transcript: str, attendees: list, meeting_id: str) -> list:
    """
    Send transcript to Groq LLM, get back structured commitment list.
    Filters out vague_intention items automatically.
    Assigns IDs and meeting_id to each commitment.
    """
    if MOCK_MODE:
        return _inject_ids(MOCK_EXTRACTION, meeting_id)

    prompt = EXTRACTION_PROMPT.format(
        attendees=", ".join([a["name"] for a in attendees])
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"TRANSCRIPT:\n{transcript}"}
        ],
        temperature=0.1,   # low temp for structured extraction
        max_tokens=2000,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
        # Handle both array and {commitments: [...]} response shapes
        if isinstance(parsed, list):
            items = parsed
        elif "commitments" in parsed:
            items = parsed["commitments"]
        else:
            items = list(parsed.values())[0]
    except json.JSONDecodeError:
        # Strip markdown fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        items = json.loads(clean)

    # Filter vague intentions — agent decides what NOT to track
    real_commitments = [
        item for item in items
        if item.get("owner_type") != "vague_intention"
    ]

    return _inject_ids(real_commitments, meeting_id)

def _inject_ids(items: list, meeting_id: str) -> list:
    now = datetime.utcnow().isoformat()
    for item in items:
        item["id"] = str(uuid.uuid4())
        item["meeting_id"] = meeting_id
        item["status"] = "open"
        item["nudge_count"] = 0
        item["created_at"] = now
        item["updated_at"] = now
    return items
```

---

## 8. RESOLVER.PY

```python
import os
import json
from groq import Groq
from prompts import RESOLUTION_PROMPT
from models import get_agent_now
from mock_responses import MOCK_RESOLUTION

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

# Mock calendar for demo — replace with real Google Calendar data if available
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
    if MOCK_MODE:
        return MOCK_RESOLUTION

    needs_resolution = [
        c for c in commitments
        if c.get("deadline_clue") or c.get("explicit_deadline")
    ]

    if not needs_resolution:
        return commitments

    now = get_agent_now()

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": RESOLUTION_PROMPT.format(
                    current_datetime=now.isoformat(),
                    calendar_context=json.dumps(DEMO_CALENDAR)
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
    try:
        resolved = json.loads(raw)
        if isinstance(resolved, dict):
            resolved = list(resolved.values())[0]
    except:
        resolved = needs_resolution  # fallback: return unmodified

    # Merge resolved back into full list
    resolved_map = {r["id"]: r for r in resolved}
    for c in commitments:
        if c["id"] in resolved_map:
            c.update(resolved_map[c["id"]])
        # Set original_deadline once
        if not c.get("original_deadline") and c.get("deadline"):
            c["original_deadline"] = c["deadline"]

    return commitments
```

---

## 9. SIMILARITY.PY — THE SHARED ENGINE (U6, U7, F9)

This single file powers duplicate merging, renegotiation detection,
and recommitment flagging. Build it once, use it everywhere.

```python
import os
import json
import numpy as np
from groq import Groq
from models import get_db

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_embedding(text: str) -> list:
    """
    Get embedding vector for text using Groq's embedding endpoint.
    Falls back to a simple bag-of-words if embedding unavailable.
    """
    # Groq doesn't yet offer embeddings — use this simple fallback
    # for hackathon. Replace with OpenAI/Cohere embeddings if available.
    words = set(text.lower().split())
    return list(words)  # will be compared via Jaccard similarity

def jaccard_similarity(set1, set2) -> float:
    s1, s2 = set(set1), set(set2)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)

RENEGOTIATION_PHRASES = [
    "push that to", "push this to", "move it to", "delay",
    "I'll do half", "partial", "next week", "next sprint",
    "not going to make", "won't be able", "can we extend"
]

MODIFICATION_THRESHOLD = 0.75  # similarity score to consider same task

def classify_against_open(new_commitment: dict) -> dict:
    """
    Compare a new commitment against all open commitments.
    Returns one of:
    - {"action": "new"} — no match, insert as new
    - {"action": "merge", "target_id": "..."} — duplicate, merge
    - {"action": "renegotiate", "target_id": "...", "new_deadline": "..."} — update existing
    - {"action": "recommit", "target_id": "...", "prior_missed": true} — same promise again

    THREE OUTCOMES FROM ONE ENGINE — this is U6, U7, and F9 combined.
    """
    conn = get_db()
    open_items = conn.execute("""
        SELECT id, owner, normalized_task, deadline, status, nudge_count
        FROM commitments
        WHERE status IN ('open', 'nudged', 'escalated', 'missed')
    """).fetchall()
    conn.close()

    new_words = get_embedding(new_commitment.get("normalized_task", ""))
    new_owner = new_commitment.get("owner", "").lower()
    new_text = new_commitment.get("commitment_text", "").lower()

    best_match = None
    best_score = 0.0

    for item in open_items:
        existing_words = get_embedding(item["normalized_task"])
        score = jaccard_similarity(new_words, existing_words)

        # Same owner boosts score
        if item["owner"].lower() == new_owner:
            score *= 1.2

        if score > best_score:
            best_score = score
            best_match = item

    if best_score < MODIFICATION_THRESHOLD or best_match is None:
        return {"action": "new"}

    # Match found — determine what kind
    is_renegotiation = any(phrase in new_text for phrase in RENEGOTIATION_PHRASES)

    if is_renegotiation:
        return {
            "action": "renegotiate",
            "target_id": best_match["id"],
            "new_deadline": new_commitment.get("deadline"),
            "reason": "speaker modified existing commitment"
        }

    if best_match["status"] == "missed":
        return {
            "action": "recommit",
            "target_id": best_match["id"],
            "prior_missed": True,
            "warning": f"This was committed before and missed. Second time flagged."
        }

    # Same task, same person, still open = duplicate
    return {
        "action": "merge",
        "target_id": best_match["id"],
        "note": "Duplicate commitment detected across meetings"
    }
```

---

## 10. AGENDA.PY — LIVE AGENDA COVERAGE AGENT

```python
import os
import json
from groq import Groq
from models import get_db
from prompts import AGENDA_SLOT_MATCHING_PROMPT

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

TEMPLATES = {}

def load_templates():
    """Load all template JSON files from backend/templates/"""
    import glob
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    for path in glob.glob(f"{template_dir}/*.json"):
        with open(path) as f:
            t = json.load(f)
            TEMPLATES[t["type"]] = t

def init_agenda_for_meeting(meeting_id: str, meeting_type: str):
    """Create agenda_state rows for a new meeting based on its type."""
    template = TEMPLATES.get(meeting_type, TEMPLATES.get("club_meeting"))
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
    if MOCK_MODE:
        return _mock_agenda_update(meeting_id)

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
        if not ownerless:
            _mark_slot_covered(meeting_id, "owners", "All extracted commitments have named owners")

    # LLM matching for remaining slots
    non_owner_slots = [s for s in pending_slots if s["slot_id"] != "owners"]
    if not non_owner_slots:
        return

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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

    try:
        raw = response.choices[0].message.content
        results = json.loads(raw)
        if isinstance(results, dict):
            results = list(results.values())[0]

        for r in results:
            if r.get("status") == "covered":
                _mark_slot_covered(meeting_id, r["slot_id"], r.get("evidence_quote", ""))
    except:
        pass  # Agenda matching is best-effort, never crash the main pipeline

def _mark_slot_covered(meeting_id: str, slot_id: str, evidence: str):
    from datetime import datetime
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
```

---

## 11. SCHEDULER.PY — THE WATCH LOOP

```python
import os
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import get_db, get_agent_now
from nudger import send_nudge, send_escalation

QUIET_HOURS_START = 22  # 10 PM
QUIET_HOURS_END = 8     # 8 AM
EXAM_MODE = False        # Toggle via API endpoint

scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(
        run_watch_loop,
        trigger="interval",
        seconds=10,
        id="watch_loop",
        replace_existing=True
    )
    scheduler.start()
    print("Watch loop started — ticking every 10s")

def stop_scheduler():
    scheduler.shutdown()

def run_watch_loop():
    """
    Core autonomous loop. Runs every 10s.
    Reads agent's simulated clock (not real time).
    Makes all decisions deterministically — LLM is NOT called here.
    """
    now = get_agent_now()

    if _is_quiet_hours(now) and not EXAM_MODE:
        return  # Respect quiet hours

    conn = get_db()
    open_items = conn.execute("""
        SELECT c.*, m.title as meeting_title, m.date as meeting_date
        FROM commitments c
        JOIN meetings m ON c.meeting_id = m.id
        WHERE c.status IN ('open', 'nudged', 'escalated')
        AND c.deadline IS NOT NULL AND c.deadline != ''
    """).fetchall()
    conn.close()

    for item in open_items:
        item = dict(item)
        try:
            deadline = datetime.fromisoformat(item["deadline"])
        except:
            continue

        time_until = deadline - now
        hours_until = time_until.total_seconds() / 3600

        # RULE 1: Nudge at T-24h if still open
        if hours_until <= 24 and item["status"] == "open":
            send_nudge(item, hours_until)
            _update_status(item["id"], "nudged")
            _log_event(item["id"], "nudged", f"Nudge sent at T-{hours_until:.1f}h")

        # RULE 2: Escalate at T-6h if still only nudged
        elif hours_until <= 6 and item["status"] == "nudged":
            send_escalation(item)
            _update_status(item["id"], "escalated")
            _log_event(item["id"], "escalated", f"Escalated at T-{hours_until:.1f}h")

        # RULE 3: Mark missed if deadline passed
        elif hours_until < 0 and item["status"] in ("open", "nudged", "escalated"):
            _update_status(item["id"], "missed")
            _log_event(item["id"], "missed", "Deadline passed without completion")
            _update_person_stats(item["owner"], "missed")
            _check_cascade(item["id"], abs(hours_until))

            # Trigger reassignment suggestion if overloaded
            _maybe_suggest_reassignment(item)

def _check_cascade(commitment_id: str, delay_hours: float):
    """
    When a task is missed/renegotiated, propagate delay to dependent tasks.
    This is U3 — cascading delay propagation.
    """
    conn = get_db()
    dependents = conn.execute("""
        SELECT * FROM commitments
        WHERE depends_on = ? AND status IN ('open', 'nudged')
    """, (commitment_id,)).fetchall()
    conn.close()

    for dep in dependents:
        dep = dict(dep)
        if dep.get("deadline"):
            old_deadline = datetime.fromisoformat(dep["deadline"])
            new_deadline = old_deadline + timedelta(hours=delay_hours)
            conn = get_db()
            conn.execute("""
                UPDATE commitments SET deadline=?, status='open', updated_at=?
                WHERE id=?
            """, (new_deadline.isoformat(), datetime.utcnow().isoformat(), dep["id"]))
            conn.commit()
            conn.close()
            _log_event(dep["id"], "cascade_shifted",
                       f"Shifted by {delay_hours:.1f}h due to upstream delay")
            # Recurse for further downstream
            _check_cascade(dep["id"], delay_hours)

def _maybe_suggest_reassignment(item: dict):
    """
    U7 equivalent: If owner has > threshold open items, generate reassignment suggestion.
    Sent as a Slack message to the meeting owner (team lead), not the overloaded person.
    """
    conn = get_db()
    stats = conn.execute(
        "SELECT * FROM person_stats WHERE person=?", (item["owner"],)
    ).fetchone()
    open_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM commitments WHERE owner=? AND status IN ('open','nudged','escalated')",
        (item["owner"],)
    ).fetchone()["cnt"]
    conn.close()

    if not stats:
        return

    threshold = stats["avg_completion_per_week"]
    if open_count > threshold * 1.5:
        from nudger import send_reassignment_suggestion
        send_reassignment_suggestion(item, open_count, float(threshold))

def _update_status(commitment_id: str, status: str):
    from datetime import datetime
    conn = get_db()
    conn.execute("""
        UPDATE commitments SET status=?, updated_at=? WHERE id=?
    """, (status, datetime.utcnow().isoformat(), commitment_id))
    conn.commit()
    conn.close()

def _log_event(commitment_id: str, event: str, detail: str):
    from datetime import datetime
    conn = get_db()
    conn.execute("""
        INSERT INTO commitment_history (commitment_id, event, detail, at)
        VALUES (?, ?, ?, ?)
    """, (commitment_id, event, detail, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def _update_person_stats(person: str, event: str):
    conn = get_db()
    field = {"on_time": "on_time", "missed": "missed", "renegotiated": "renegotiated"}.get(event)
    if field:
        conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
        conn.commit()
    conn.close()

def _is_quiet_hours(now: datetime) -> bool:
    return now.hour >= QUIET_HOURS_START or now.hour < QUIET_HOURS_END
```

---

## 12. NUDGER.PY — MESSAGE GENERATION + DELIVERY

```python
import os
import json
import requests
from groq import Groq
from twilio.rest import Client
from prompts import NUDGE_GENERATION_PROMPT, REASSIGNMENT_SUGGESTION_PROMPT
from mock_responses import MOCK_NUDGE_TEXT

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
WA_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
WA_TO = os.getenv("TWILIO_WHATSAPP_TO", "")

def _generate_message(commitment: dict, hours_until: float) -> str:
    """LLM #3: Generate a personalized nudge in the committer's voice."""
    if MOCK_MODE:
        return MOCK_NUDGE_TEXT

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": NUDGE_GENERATION_PROMPT.format(
                    owner_name=commitment["owner"],
                    commitment_text=commitment["commitment_text"],
                    meeting_title=commitment.get("meeting_title", "your recent meeting"),
                    meeting_date=commitment.get("meeting_date", ""),
                    deadline=commitment["deadline"],
                    hours_until=round(hours_until, 1)
                )
            }
        ],
        temperature=0.7,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

def send_nudge(commitment: dict, hours_until: float):
    """Send personalized nudge via WhatsApp → Slack fallback."""
    message = _generate_message(commitment, hours_until)

    # Try WhatsApp first (most impressive on demo day)
    if TWILIO_SID and WA_TO and not MOCK_MODE:
        try:
            twilio = Client(TWILIO_SID, TWILIO_TOKEN)
            twilio.messages.create(
                body=f"🔔 {message}",
                from_=WA_FROM,
                to=WA_TO
            )
            print(f"WhatsApp nudge sent to {WA_TO}")
            return
        except Exception as e:
            print(f"WhatsApp failed, falling back to Slack: {e}")

    # Slack fallback
    if SLACK_WEBHOOK:
        payload = {
            "text": f"*Nudge for {commitment['owner']}*\n{message}",
            "attachments": [{
                "color": "#FFA500",
                "text": f"Task: {commitment['normalized_task']}\nDeadline: {commitment['deadline']}"
            }]
        }
        requests.post(SLACK_WEBHOOK, json=payload)

def send_escalation(commitment: dict):
    """Escalate to meeting owner — different message, wider visibility."""
    message = (
        f"⚠️ *Escalation Alert*\n"
        f"{commitment['owner']} committed to: _{commitment['normalized_task']}_\n"
        f"Deadline passed without completion. "
        f"Original commitment: \"{commitment['commitment_text']}\"\n"
        f"Recommend: reassign or schedule a quick sync."
    )
    if SLACK_WEBHOOK:
        requests.post(SLACK_WEBHOOK, json={"text": message})

def send_ownerless_alert(commitment: dict, meeting_owner: str):
    """Alert meeting owner when an ownerless commitment is detected."""
    message = (
        f"⚠️ *Ownerless Commitment Detected*\n"
        f"In this transcript: \"{commitment['commitment_text']}\"\n"
        f"Nobody has been assigned. Who's taking this?\n"
        f"Reply with a name or assign from the dashboard."
    )
    if SLACK_WEBHOOK:
        requests.post(SLACK_WEBHOOK, json={"text": message})

def send_reassignment_suggestion(commitment: dict, open_count: int, weekly_capacity: float):
    """U7: Proactively suggest redistribution when someone is overloaded."""
    # Get available team members from DB
    from models import get_db
    conn = get_db()
    available = conn.execute("""
        SELECT p.person, p.avg_completion_per_week,
               COUNT(c.id) as current_open
        FROM person_stats p
        LEFT JOIN commitments c ON c.owner=p.person AND c.status IN ('open','nudged')
        WHERE p.person != ?
        GROUP BY p.person
        HAVING current_open < p.avg_completion_per_week
        ORDER BY current_open ASC
        LIMIT 3
    """, (commitment["owner"],)).fetchall()
    conn.close()

    if not available:
        return

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": REASSIGNMENT_SUGGESTION_PROMPT.format(
                overloaded_person=commitment["owner"],
                open_commitments=open_count,
                completion_rate=weekly_capacity,
                available_members=json.dumps([dict(a) for a in available]),
                task_to_reassign=commitment["normalized_task"]
            )
        }],
        temperature=0.5,
        max_tokens=100
    )

    suggestion = response.choices[0].message.content.strip()
    message = f"💡 *Redistribution Suggestion*\n{suggestion}"

    if SLACK_WEBHOOK:
        requests.post(SLACK_WEBHOOK, json={"text": message})

def send_beneficiary_notification(commitment: dict):
    """U10: Notify the person who was waiting when a task is marked done."""
    if not commitment.get("beneficiary"):
        return
    message = (
        f"✅ {commitment['owner']} completed: _{commitment['normalized_task']}_\n"
        f"You were waiting on this. It's done!"
    )
    if SLACK_WEBHOOK:
        requests.post(SLACK_WEBHOOK, json={
            "text": f"*For {commitment['beneficiary']}*: {message}"
        })
```

---

## 13. NOTION_MIRROR.PY — FIRE AND FORGET

```python
import os
import requests
from datetime import datetime

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID = os.getenv("NOTION_DB_ID", "")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def mirror_commitment(commitment: dict):
    """
    Create a Notion database entry for a commitment.
    This is fire-and-forget — if it fails, the SQLite record is safe.
    """
    if MOCK_MODE or not NOTION_TOKEN:
        return

    confidence_label = (
        "high" if commitment.get("confidence", 0) >= 0.8
        else "medium" if commitment.get("confidence", 0) >= 0.5
        else "low"
    )

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Owner": {
                "title": [{"text": {"content": commitment.get("owner", "Unknown")}}]
            },
            "Commitment": {
                "rich_text": [{"text": {"content": commitment.get("normalized_task", "")}}]
            },
            "Deadline": {
                "date": {"start": commitment["deadline"]} if commitment.get("deadline") else None
            },
            "Status": {
                "select": {"name": commitment.get("status", "open")}
            },
            "Source Meeting": {
                "rich_text": [{"text": {"content": commitment.get("meeting_id", "")}}]
            },
            "Confidence": {
                "select": {"name": confidence_label}
            }
        }
    }

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=5
        )
        if r.status_code != 200:
            print(f"Notion mirror failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Notion mirror exception (non-fatal): {e}")
```

---

## 14. CALENDAR_AGENT.PY — GOOGLE CALENDAR INTEGRATION

```python
import os
import json
from datetime import datetime, timedelta

CREDS_PATH = os.getenv("GOOGLE_CALENDAR_CREDS", "backend/credentials.json")
TOKEN_PATH = "backend/token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def _get_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import os.path

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def get_upcoming_events(days_ahead: int = 7) -> list:
    """Fetch calendar events to provide context for deadline resolution."""
    try:
        service = _get_service()
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + "Z"

        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            maxResults=20,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        return [
            {
                "title": e.get("summary", ""),
                "datetime": e["start"].get("dateTime", e["start"].get("date"))
            }
            for e in result.get("items", [])
        ]
    except Exception as e:
        print(f"Calendar fetch failed, using demo calendar: {e}")
        return []  # Falls back to DEMO_CALENDAR in resolver.py

def propose_followup_meeting(commitment: dict, suggested_time: str) -> dict:
    """
    Draft a calendar event proposal — does NOT create it yet.
    Returns draft for human confirmation via Slack.
    This is the "verify before create" pattern.
    """
    return {
        "draft": True,
        "summary": f"Quick sync: {commitment['normalized_task']}",
        "description": f"Follow-up on missed commitment: {commitment['commitment_text']}",
        "start": suggested_time,
        "duration_min": 15,
        "attendees": [commitment["owner"]],
        "commitment_id": commitment["id"]
    }

def create_confirmed_event(draft: dict, attendee_emails: list) -> str:
    """
    Called ONLY after human confirmation.
    Creates the actual Google Calendar event with Meet link.
    Returns the Meet link.
    """
    try:
        service = _get_service()
        start = datetime.fromisoformat(draft["start"])
        end = start + timedelta(minutes=draft["duration_min"])

        event = {
            "summary": draft["summary"],
            "description": draft["description"],
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
            "attendees": [{"email": e} for e in attendee_emails],
            "conferenceData": {
                "createRequest": {"requestId": f"mdc-{draft['commitment_id']}"}
            }
        }

        result = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all"
        ).execute()

        return result.get("hangoutLink", result.get("htmlLink", ""))
    except Exception as e:
        print(f"Calendar event creation failed: {e}")
        return ""
```

---

## 15. MAIN.PY — FASTAPI ROUTES

```python
import os
import uuid
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from models import init_db, get_db, get_agent_now, advance_agent_clock
from extractor import extract_commitments
from resolver import resolve_deadlines
from similarity import classify_against_open
from agenda import (
    load_templates, init_agenda_for_meeting,
    process_chunk_for_agenda, get_agenda_status, check_wrapup_cue
)
from notion_mirror import mirror_commitment
from nudger import send_ownerless_alert, send_beneficiary_notification
from scheduler import start_scheduler

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

# ─── REQUEST MODELS ───────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    title: str
    type: str                      # sprint_review | event_planning | project_kickoff | club_meeting
    owner: str                     # meeting chair name
    attendees: List[dict]          # [{name, email, slack_handle}]
    transcript: Optional[str] = ""

class ChunkRequest(BaseModel):
    chunk: str                     # 30s transcript text
    chunk_index: int

class CommitmentAction(BaseModel):
    action: str                    # done | need_time | assign_owner | approve | reject | reassign
    new_deadline: Optional[str] = None
    new_owner: Optional[str] = None

class CalendarConfirm(BaseModel):
    draft: dict
    attendee_emails: List[str]

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.post("/meetings")
async def create_meeting(data: MeetingCreate):
    """Create a meeting. If transcript provided, process immediately."""
    meeting_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute("""
        INSERT INTO meetings (id, title, type, date, owner, attendees, transcript, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        meeting_id, data.title, data.type,
        datetime.utcnow().isoformat(), data.owner,
        json.dumps(data.attendees), data.transcript,
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

    # Initialize agenda template
    init_agenda_for_meeting(meeting_id, data.type)

    # If full transcript provided (non-chunked path), process now
    if data.transcript:
        await _process_full_transcript(meeting_id, data.transcript, data.attendees, data.owner)

    return {"meeting_id": meeting_id, "status": "created"}

@app.post("/meetings/{meeting_id}/chunk")
async def ingest_chunk(meeting_id: str, data: ChunkRequest):
    """
    Live chunked ingestion. Called every 30s during a meeting.
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

    # Generate MoM
    from prompts import MOM_GENERATION_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
    Cross-Meeting Context Injection (Future Scope).
    Generates 'since we last spoke' briefing for the meeting chair.
    """
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    conn.close()

    if not meeting:
        raise HTTPException(404, "Meeting not found")

    meeting = dict(meeting)
    attendees_list = [a["name"] for a in json.loads(meeting["attendees"])]

    # Find open commitments involving these attendees from prior meetings
    conn = get_db()
    open_items = conn.execute("""
        SELECT c.*, m.title as meeting_title, m.date as meeting_date
        FROM commitments c
        JOIN meetings m ON c.meeting_id = m.id
        WHERE c.owner IN ({})
        AND c.status IN ('open', 'nudged', 'escalated', 'missed')
        AND c.meeting_id != ?
        ORDER BY c.deadline ASC
    """.format(",".join(["?"] * len(attendees_list))),
    attendees_list + [meeting_id]).fetchall()

    # Flag items promised twice
    recommits = conn.execute("""
        SELECT owner, normalized_task, COUNT(*) as count
        FROM commitments
        WHERE owner IN ({})
        GROUP BY owner, normalized_task
        HAVING count > 1
    """.format(",".join(["?"] * len(attendees_list))),
    attendees_list).fetchall()
    conn.close()

    flags = [
        f"{r['owner']} has committed to '{r['normalized_task']}' {r['count']} times"
        for r in recommits
    ]

    from prompts import CROSS_MEETING_SUMMARY_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
        _update_commitment(commitment_id, {
            "status": "renegotiated",
            "deadline": data.new_deadline,
            "updated_at": now
        })
        # Cascade the delay
        old_dl = datetime.fromisoformat(item["deadline"])
        new_dl = datetime.fromisoformat(data.new_deadline)
        delay_hours = (new_dl - old_dl).total_seconds() / 3600
        if delay_hours > 0:
            from scheduler import _check_cascade
            _check_cascade(commitment_id, delay_hours)

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

    return {"status": "ok", "action": data.action}

@app.post("/calendar/confirm")
async def confirm_calendar_event(data: CalendarConfirm):
    """Human confirmed a follow-up meeting proposal. Create it now."""
    from calendar_agent import create_confirmed_event
    link = create_confirmed_event(data.draft, data.attendee_emails)
    return {"meet_link": link, "status": "created"}

@app.post("/simulate")
async def simulate_time(advance_hours: float = 24):
    """
    ★ THE DEMO ENDPOINT ★
    Advances the agent's clock without waiting real time.
    Run the watch loop immediately after advancing.
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

    # Add follow-through rate
    for s in stats:
        total = s["committed"] or 1
        s["follow_through_rate"] = round(s["on_time"] / total, 2)
        s["at_risk"] = s["follow_through_rate"] < 0.5 and s["committed"] >= 3

    # Generate narrative summary
    from prompts import PATTERN_REPORT_PROMPT
    from groq import Groq
    groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
        r["follow_through_rate"] = round(r["completed"] / total, 2)
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

# ─── HELPERS ─────────────────────────────────────────────────────────────────

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
            # Update existing, don't insert new
            _update_commitment(result["target_id"], {
                "deadline": commitment.get("deadline", ""),
                "status": "renegotiated",
                "updated_at": datetime.utcnow().isoformat()
            })
            return {**commitment, "action_taken": "renegotiated_existing"}

        elif result["action"] == "merge":
            return {**commitment, "action_taken": "merged_with_existing"}

        elif result["action"] == "recommit":
            commitment["warning"] = result.get("warning", "")

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
        commitment.get("beneficiary", ""),
        commitment.get("commitment_text", ""),
        commitment.get("normalized_task", ""),
        commitment.get("explicit_deadline", ""),
        commitment.get("deadline", ""),
        commitment.get("original_deadline", ""),
        commitment.get("deadline_clue", ""),
        commitment.get("status", "open"),
        commitment.get("owner_type", "person"),
        commitment.get("item_type", "self_commitment"),
        commitment.get("assigned_by", ""),
        commitment.get("confidence", 0.9),
        commitment.get("depends_on_hint", ""),
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

async def _process_full_transcript(meeting_id: str, transcript: str, attendees: list, owner: str):
    """Process a full transcript in one shot (non-chunked path)."""
    raw = extract_commitments(transcript, attendees, meeting_id)
    resolved = resolve_deadlines(raw)
    for c in resolved:
        _save_commitment(c, owner)
    process_chunk_for_agenda(meeting_id, "club_meeting", transcript, resolved)
```

---

## 16. MOCK_RESPONSES.PY — MOCK MODE DATA

```python
# When MOCK_MODE=true, these replace all real API calls.
# The pipeline still runs end-to-end — just with canned responses.

MOCK_EXTRACTION = [
    {
        "speaker": "Alice",
        "commitment_text": "I'll finish the API integration by Thursday",
        "normalized_task": "Finish API integration",
        "explicit_deadline": "Thursday",
        "deadline_clue": None,
        "depends_on_hint": None,
        "beneficiary": "Bob",
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.95,
        "timestamp_sec": 45
    },
    {
        "speaker": "Bob",
        "commitment_text": "Once Alice finishes, I'll do the integration testing",
        "normalized_task": "Complete integration testing",
        "explicit_deadline": None,
        "deadline_clue": "once Alice finishes",
        "depends_on_hint": "once Alice finishes",
        "beneficiary": None,
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.88,
        "timestamp_sec": 62
    },
    {
        "speaker": "Rohith",
        "commitment_text": "we'll handle the deployment, don't worry",
        "normalized_task": "Handle production deployment",
        "explicit_deadline": None,
        "deadline_clue": "before the client call",
        "depends_on_hint": None,
        "beneficiary": None,
        "owner_type": "ownerless",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.91,
        "timestamp_sec": 89
    },
    {
        "speaker": "Priya",
        "commitment_text": "I'll review the API contract by Friday",
        "normalized_task": "Review API contract",
        "explicit_deadline": "Friday",
        "deadline_clue": None,
        "depends_on_hint": None,
        "beneficiary": "Rohith",
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.97,
        "timestamp_sec": 120
    }
]

MOCK_RESOLUTION = MOCK_EXTRACTION  # Deadlines added by main pipeline in mock mode

MOCK_NUDGE_TEXT = (
    "Hey Alice — in Thursday's Sprint Review you said you'd finish the API "
    "integration. That deadline is tomorrow. Want to send a quick status "
    "update to Bob now?"
)
```

---

## 17. AGENDA TEMPLATES (backend/templates/)

### sprint_review.json
```json
{
  "type": "sprint_review",
  "display_name": "Sprint Review",
  "slots": [
    {"id": "blockers", "label": "Blockers discussed", "required": true},
    {"id": "demos", "label": "Work demoed to team", "required": false},
    {"id": "next_scope", "label": "Next sprint scope agreed", "required": true},
    {"id": "owners", "label": "Every task has a named owner", "required": true},
    {"id": "testing", "label": "Testing/QA plan mentioned", "required": true},
    {"id": "retrospective", "label": "What went wrong discussed", "required": false}
  ]
}
```

### event_planning.json
```json
{
  "type": "event_planning",
  "display_name": "Event Planning",
  "slots": [
    {"id": "venue", "label": "Venue confirmed", "required": true},
    {"id": "budget", "label": "Budget discussed", "required": true},
    {"id": "permissions", "label": "Permissions/approvals assigned", "required": true},
    {"id": "publicity", "label": "Publicity plan mentioned", "required": false},
    {"id": "volunteers", "label": "Volunteer roles assigned", "required": true},
    {"id": "date", "label": "Date and time confirmed", "required": true}
  ]
}
```

### project_kickoff.json
```json
{
  "type": "project_kickoff",
  "display_name": "Project Kickoff",
  "slots": [
    {"id": "goals", "label": "Project goals defined", "required": true},
    {"id": "roles", "label": "Team roles assigned", "required": true},
    {"id": "timeline", "label": "Timeline and milestones set", "required": true},
    {"id": "risks", "label": "Risks identified", "required": false},
    {"id": "first_milestone", "label": "First milestone named with owner", "required": true}
  ]
}
```

### club_meeting.json
```json
{
  "type": "club_meeting",
  "display_name": "Club Meeting",
  "slots": [
    {"id": "attendance", "label": "Attendance noted", "required": false},
    {"id": "budget", "label": "Budget/expenses discussed", "required": false},
    {"id": "next_event", "label": "Next event planned", "required": true},
    {"id": "action_items", "label": "Action items assigned", "required": true},
    {"id": "owners", "label": "Every action item has an owner", "required": true}
  ]
}
```

---

## 18. SYNTHETIC TRANSCRIPTS (synthetic_data/)

### transcript_1_clean.txt
```
[00:00] Alice: Good morning everyone. Let's get started with the sprint review.
[00:15] Alice: I'll finish the payments API by Thursday end of day.
[00:32] Bob: Once Alice finishes the API, I'll complete the integration testing by Friday morning.
[00:48] Priya: I'll review the API contract and send comments to Rohith by Thursday noon.
[01:05] Rohith: I'll prepare the deployment checklist by Wednesday evening.
[01:20] Alice: Great. Let's also make sure testing covers the edge cases we discussed.
[01:35] Priya: I'll update the test plan document by Thursday as well.
[01:50] Alice: Okay, anything else before we wrap up?
[02:00] Rohith: I think we're good. Talk later everyone.
```

### transcript_2_messy.txt
```
[00:00] Rohith: Alright, quick sync. Let's go.
[00:12] Alice: So I'll get the API done before the client call.
[00:24] Bob: We should probably look into caching at some point, just a thought.
[00:38] Rohith: Yeah definitely. Anyway, we'll handle the deployment, don't worry about it.
[00:55] Alice: Who's doing the deployment exactly?
[01:02] Rohith: Like, the team. We'll sort it out.
[01:15] Priya: I'll write the test cases, I can get that done by end of week.
[01:28] Bob: Once Alice is done with the API, I'll do the front-end integration.
[01:40] Alice: Also, let's grab 15 minutes Thursday afternoon to go over the client demo flow.
[01:55] Rohith: Yeah let's do that. Okay, anything else before we close?
[02:05] Bob: I think that's it.
```

### transcript_3_followup.txt
```
[00:00] Alice: Quick check-in from last week's sync.
[00:12] Rohith: Yeah, so about the deployment — I'll actually own that. Should be done by Monday.
[00:28] Alice: Good. I actually didn't finish the API on Thursday, I'll push that to next week.
[00:45] Bob: So my integration gets pushed too then, makes sense.
[01:00] Priya: I finished the test cases already, that's done.
[01:12] Alice: Perfect. I'll finish the API by next Wednesday, promise.
[01:28] Rohith: This is actually the second time Alice has mentioned the API.
[01:35] Alice: I know, I know. Wednesday for real this time.
[01:50] Rohith: Let's wrap up. I'll send the updated timeline to everyone by tomorrow morning.
```

---

## 19. FUTURE SCOPE (documented, not built on demo day)

These features are explicitly called out in README as "Roadmap" — judges read
these as evidence of product depth. Do NOT attempt to build them on the day.

### Cross-Meeting Context Injection
API endpoint `/meetings/{id}/pre-brief` is already stubbed in main.py above.
Description: When a new meeting starts, the agent pre-loads open commitments
relevant to the attendees from all prior meetings and generates a
"since we last spoke" briefing for the meeting chair.

### Cross-Platform Commitment Consolidation
Extend the ingestion layer to accept Slack thread exports and email threads
in the same format as transcripts. The extraction prompt already handles
informal language. Route to same commitment table. One ledger for all
verbal-style commitments across every channel.

### Commitment Trade / Reassignment Suggestion
`send_reassignment_suggestion()` is already built in nudger.py.
Full version: add `skills` tags to person_stats, match task keywords to
skill tags when suggesting who to reassign to.

### Click-to-Audio Provenance (U5)
`timestamp_sec` is already stored per commitment.
Frontend: wrap each commitment row in an `<audio>` element pointing to the
meeting audio file, seeked to `timestamp_sec`. Click = play the 5 seconds
where that promise was made. Kills hallucination concerns live on stage.

---

## 20. README STRUCTURE

Your README.md must follow this order:

```markdown
# Meeting Debt Collector 🎯
> "Not a chatbot. Not a note-taker. An autonomous agent that stands between
> 'I'll do that' and the follow-up."

## The Problem
[3 sentences. Quote the stat: 60-70% of verbal commitments forgotten in 48h.]

## What It Does
[Architecture diagram — paste the ASCII one from the build spec]

## Features
[Copy F1–F8 with one-line descriptions]

## USPs
[Copy U1–U9 with one-line descriptions each]

## Tech Stack
- LLM: Groq (Llama 3.3 70B) — extraction, resolution, nudge generation
- Backend: FastAPI + SQLite
- Notifications: Twilio WhatsApp + Slack Webhooks
- Task Mirror: Notion API
- Calendar: Google Calendar API
- Scheduler: APScheduler

## Setup
[pip install, .env setup, python backend/main.py]

## Demo
[Paste the 4-min demo script]

## API Reference
[Paste the route list]

## Roadmap
[Cross-meeting context, cross-platform consolidation, skill-based reassignment]

## Team
[Names and roles]
```

---

## 21. STARTUP COMMAND

```bash
# Install
pip install -r requirements.txt

# Set up env
cp .env.example .env
# Fill in your keys

# Run (from project root)
cd backend && uvicorn main:app --reload --port 8000

# Test health
curl http://localhost:8000/health

# Mock mode (no API keys needed)
MOCK_MODE=true uvicorn main:app --reload --port 8000
```
