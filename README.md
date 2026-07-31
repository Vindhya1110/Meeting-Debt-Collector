# Meeting Debt Collector 🎯
> "Not a chatbot. Not a note-taker. An autonomous agent that stands between
> 'I'll do that' and the follow-up."

## The Problem
60-70% of verbal commitments made in meetings are forgotten or unacted-on
within 48 hours. Meeting minutes get written, filed, and never opened again.
Nobody is watching the promises after the call ends — so the "debt" of undone
commitments just quietly compounds, meeting after meeting.

## What It Does

```
 Chrome extension (live captions)     or     Dashboard (manual transcript)
  Meet / Zoom / Teams DOM                     paste a transcript, no meeting needed
        │                                              │
        └──────────────────┬───────────────────────────┘
                            ▼
                 POST /meetings/start
                 POST /meetings/{id}/chunk   (every ~30s)
                            │
                            ▼
 ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
 │  Extractor   │───▶│   Resolver   │───▶│   Similarity     │
 │ (LLM, main)  │    │ (LLM, main)  │    │  Engine (embed)  │
 │ commitments  │    │ deadlines    │    │ dup/renego/      │
 │ from speech  │    │ → ISO times  │    │ recommit         │
 └─────────────┘    └──────────────┘    └─────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   SQLite ledger      │  (source of truth for the watch loop)
                 └─────────────────────┘
                     │        │        │
                     ▼        ▼        ▼
             ┌───────────┐ ┌────────┐ ┌──────────────┐
             │ Scheduler  │ │ Agenda │ │   Notion      │
             │ watch loop │ │ agent  │ │  Reporter     │
             │ nudge/     │ │ live   │ │ 4 live DBs:   │
             │ escalate/  │ │coverage│ │ Meetings,     │
             │ cascade    │ │checking│ │ Commitments,  │
             └───────────┘ └────────┘ │ People, Agenda│
                     │                └──────────────┘
                     ▼
             ┌─────────────┐
             │  Nudger      │  →  WhatsApp (Twilio) → Slack fallback
             │ (LLM, fast)  │
             └─────────────┘
```

## Features
- **Commitment extraction** — pulls genuine commitments out of raw meeting
  speech, skipping vague aspirations ("we should look into caching").
- **Deadline resolution** — turns "by Thursday" / "before the client call"
  into real ISO timestamps, using calendar context when available.
- **Autonomous watch loop** — nudges at T-24h, escalates at T-6h, marks
  missed after the deadline — no human has to check a dashboard for this to run.
- **Personalized nudges** — a fast LLM writes a warm, human-sounding reminder
  that quotes the person's own words back to them.
- **Live agenda coverage** — tracks whether required agenda topics were
  actually discussed and warns before the meeting wraps up if not.
- **Meeting minutes generation** — auto-generates clean MoM once a meeting ends.
- **Notion-first reporting** — every meeting, commitment, person, and agenda
  slot is mirrored live into 4 auto-created Notion databases.
- **Google Calendar integration** — reads upcoming events to resolve implicit
  deadlines, and can draft (human-confirmed) follow-up meetings.
- **Cascading delay propagation** — when a commitment is missed or pushed,
  the delay automatically propagates to everything that depends on it.
- **Confidence-gated review queue** — low-confidence extractions get routed
  to a human review queue instead of silently entering the pipeline.
- **One similarity engine, three jobs** — a single embedding-based classifier
  detects duplicate commitments, renegotiations, and repeat-missed
  recommitments.
- **Meeting-level debt score** — not just "did the person deliver" but "was
  this meeting itself productive," surfaced per meeting.

## Tech Stack
- LLM: [Featherless AI](https://featherless.ai) (OpenAI-compatible) — a 70B
  model for extraction/resolution/reports, a fast 8B model for nudge text
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` — real cosine-similarity
  matching for duplicate/renegotiation/recommit detection
- Backend: FastAPI + SQLite
- Live capture: Chrome extension (Manifest V3) reading captions from the
  Google Meet / Zoom / Teams DOM — or paste a transcript into the dashboard
- Notifications: Slack Incoming Webhook (WhatsApp via Twilio if configured)
- Reporting: Notion API — 4 databases auto-created on first run
- Calendar: Google Calendar API (OAuth, one-time interactive setup)
- Scheduler: APScheduler, driven by a simulated agent clock for demoability

## Setup

### 1. Agent (backend)
```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt        # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

copy .env.example .env      # Windows; cp on macOS/Linux
# Fill in your keys — Featherless key, Notion token + parent page ID,
# Slack webhook. Twilio/Calendar are optional.

cd agent
..\venv\Scripts\python -m uvicorn main:app --port 8000
# On first run, Notion databases are created automatically under
# NOTION_PARENT_PAGE_ID (must be shared with your integration first).
```

Open **http://localhost:8000** for the manual-testing dashboard, or:
```bash
curl http://localhost:8000/health
```

Mock mode (no external API calls at all, canned responses):
```bash
set MOCK_MODE=true
..\venv\Scripts\python -m uvicorn main:app --port 8000
```

### 2. Chrome extension (live capture from real meetings)
```
1. Open Chrome → chrome://extensions/
2. Enable "Developer mode" (toggle, top right)
3. Click "Load unpacked" → select the extension/ folder
4. Join a Google Meet / Zoom / Teams call
5. Click the extension icon → enter meeting title + type → Start Capturing
6. Speak normally — every 30s a caption chunk is sent to the agent
7. Click "Stop & Save to Notion" when done
```

### 3. Dashboard (manual testing, no live meeting needed)
Open http://localhost:8000, paste a transcript (or load one of the sample
ones), and process it the same way the extension would — useful for testing
without joining an actual call.

### 4. Google Calendar (optional, one-time)
```bash
cd agent
..\venv\Scripts\python setup_calendar.py
# opens a browser once for consent, saves token.json
```

## Demo
```bash
# Advance the agent's simulated clock and run the watch loop immediately
curl -X POST "http://localhost:8000/simulate?advance_hours=24"

# Check all open commitments
curl "http://localhost:8000/commitments?status=open"

# Mark done (simulate a WhatsApp/Slack reply)
curl -X POST http://localhost:8000/commitments/COMMITMENT_ID/action \
  -H "Content-Type: application/json" -d '{"action":"done"}'
```

## API Reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/meetings/start` | Start a meeting (extension or dashboard); optional `transcript` for one-shot processing |
| POST | `/meetings/{id}/chunk` | Feed a ~30s live caption chunk |
| POST | `/meetings/{id}/end` | Generate MoM, finalize, write pattern report to Notion |
| POST | `/meetings/{id}/pre-brief` | "Since we last spoke" briefing for the chair |
| GET | `/meetings` | List all meetings |
| GET | `/commitments` | Dashboard feed, filterable by status/owner |
| POST | `/commitments/{id}/action` | done / need_time / assign_owner / reassign / approve / reject |
| POST | `/simulate?advance_hours=24` | Advance the agent's simulated clock and run the watch loop |
| GET | `/simulate/reset` | Reset simulated clock to real time |
| GET | `/agenda/{id}` | Agenda coverage status for a meeting |
| GET | `/report/people` | Per-person follow-through report + coaching summary |
| GET | `/report/meetings` | Per-meeting debt score |
| GET | `/health` | Liveness + mock mode + agent clock |

## Roadmap
- **Cross-Platform Commitment Consolidation** — extend ingestion to Slack
  threads and email, same schema.
- **Skill-Based Reassignment** — add skill tags to `person_stats` for smarter
  reassignment matching.
- **Click-to-Audio Provenance** — `timestamp_sec` is already stored per
  commitment; wire up an `<audio>` scrubber for playback.

## Team
Built by the project owner with Claude Code, from a hand-written build specification.
