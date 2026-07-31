# Meeting Debt Collector 🎯
> "Not a chatbot. Not a note-taker. An autonomous agent that stands between
> 'I'll do that' and the follow-up."

## The Problem
Studies on meeting behavior put the number bluntly: 60-70% of verbal commitments
made in meetings are forgotten or unacted-on within 48 hours. Meeting minutes get
written, filed, and never opened again. Nobody is watching the promises after the
call ends — so the "debt" of undone commitments just quietly compounds, meeting
after meeting.

## What It Does

```
 Transcript / live chunk
        │
        ▼
 ┌─────────────┐    ┌──────────────┐    ┌────────────────┐
 │  Extractor   │───▶│   Resolver   │───▶│   Similarity    │
 │ (LLM #1)     │    │  (LLM #2)    │    │  Engine (embed) │
 │ commitments  │    │ deadlines    │    │ dup/renego/     │
 │ from speech  │    │ → ISO times  │    │ recommit        │
 └─────────────┘    └──────────────┘    └────────────────┘
        │                                        │
        ▼                                        ▼
 ┌─────────────────────────────────────────────────────────┐
 │                     SQLite ledger                        │
 │        (meetings, commitments, history, agenda)          │
 └─────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
 ┌─────────────┐     ┌──────────────┐     ┌───────────────┐
 │  Scheduler   │     │ Agenda Agent │     │ Notion Mirror │
 │ watch loop   │     │ live coverage│     │ (fire & forget)│
 │ nudge/escalate│    │  checking    │     └───────────────┘
 │ /cascade     │     └──────────────┘
 └─────────────┘
        │
        ▼
 ┌─────────────┐
 │  Nudger      │  →  WhatsApp (Twilio) → Slack fallback
 │ (LLM #3)     │
 └─────────────┘
```

## Features
- **F1 — Commitment extraction**: pulls genuine commitments out of raw meeting
  transcripts, skipping vague aspirations ("we should look into caching").
- **F2 — Deadline resolution**: turns "by Thursday" / "before the client call"
  into real ISO timestamps, using calendar context when available.
- **F3 — Autonomous watch loop**: nudges at T-24h, escalates at T-6h, marks
  missed after the deadline — no human has to check a dashboard for this to run.
- **F4 — Personalized nudges**: LLM writes a warm, human-sounding reminder that
  quotes the person's own words back to them.
- **F5 — Live agenda coverage**: tracks whether required agenda topics were
  actually discussed and warns before the meeting wraps up if not.
- **F6 — Meeting minutes generation**: auto-generates clean MoM with a
  commitments table once a meeting is finalized.
- **F7 — Notion mirror**: every commitment is fire-and-forget mirrored to a
  Notion database so it survives even if this app goes away.
- **F8 — Google Calendar integration**: reads upcoming events to resolve
  implicit deadlines, and can draft (human-confirmed) follow-up meetings.

## USPs
- **U3 — Cascading delay propagation**: when a commitment is missed or pushed,
  the delay automatically propagates to everything that depends on it.
- **U4 — Confidence-gated review queue**: low-confidence extractions get routed
  to a human review queue instead of silently entering the pipeline.
- **U6 / U7 / F9 — One similarity engine, three jobs**: a single embedding-based
  classifier detects duplicate commitments, renegotiations, and repeat-missed
  recommitments — instead of three bespoke heuristics.
- **U9 — Meeting-level debt score**: not just "did the person deliver" but "was
  this meeting itself productive," surfaced as a follow-through rate per meeting.
- **U10 — Beneficiary notifications**: the person who was *waiting* on a
  commitment gets pinged the moment it's marked done.

## Tech Stack
- LLM: Groq (Llama 3.3 70B) — extraction, resolution, nudge generation, reports
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` — real cosine-similarity
  matching for duplicate/renegotiation/recommit detection (not a bag-of-words hack)
- Backend: FastAPI + SQLite
- Notifications: Slack Incoming Webhook (WhatsApp via Twilio if configured)
- Task Mirror: Notion API
- Calendar: Google Calendar API (OAuth, one-time interactive setup)
- Scheduler: APScheduler, driven by a simulated agent clock for demoability

## Setup

```bash
# 1. Create a virtualenv and install dependencies
python -m venv venv
venv\Scripts\pip install -r requirements.txt        # Windows
# source venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

# 2. Configure environment
copy .env.example .env      # Windows: copy, macOS/Linux: cp
# Fill in your keys in .env

# 3. (Optional, one-time) connect Google Calendar
cd backend
..\venv\Scripts\python setup_calendar.py
# opens a browser once for consent, saves token.json

# 4. Run the server (serves both the API and the dashboard)
..\venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** for the dashboard. Health check:

```bash
curl http://localhost:8000/health
```

Mock mode (no external API calls at all, canned responses):

```bash
set MOCK_MODE=true
..\venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

## Demo
See [`docs/demo_script.md`](docs/demo_script.md) for the 4-minute walkthrough.

## API Reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/meetings` | Create a meeting; processes transcript immediately if provided |
| POST | `/meetings/{id}/chunk` | Feed a ~30s live transcript chunk |
| POST | `/meetings/{id}/finalize` | Generate meeting minutes, close the meeting |
| GET | `/meetings/{id}/pre-brief` | "Since we last spoke" briefing for the chair |
| GET | `/meetings` | List all meetings |
| GET | `/commitments` | Dashboard feed, filterable by status/owner/meeting |
| POST | `/commitments/{id}/action` | done / need_time / assign_owner / reassign / approve / reject |
| POST | `/calendar/confirm` | Human-confirmed follow-up meeting creation |
| POST | `/simulate?advance_hours=24` | Advance the agent's simulated clock and run the watch loop |
| GET | `/simulate/reset` | Reset simulated clock to real time |
| GET | `/agenda/{id}` | Agenda coverage status for a meeting |
| GET | `/report/people` | Per-person follow-through report + coaching summary |
| GET | `/report/meetings` | Per-meeting debt score |
| GET | `/health` | Liveness + mock mode + agent clock |

## Roadmap
- **Cross-Meeting Context Injection** — stubbed and working via `/meetings/{id}/pre-brief`.
- **Cross-Platform Commitment Consolidation** — extend ingestion to Slack threads and email, same schema.
- **Commitment Trade / Skill-Based Reassignment** — `send_reassignment_suggestion()` exists; add skill tags to `person_stats` for smarter matching.
- **Click-to-Audio Provenance** — `timestamp_sec` is already stored per commitment; wire up an `<audio>` scrubber in the dashboard.

## Team
Built by the project owner with Claude Code, from a hand-written build specification.
