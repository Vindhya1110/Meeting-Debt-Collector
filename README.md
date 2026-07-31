# Meeting Debt Collector 🎯

> "Not a chatbot. Not a note-taker. An autonomous agent that stands between
> **'I'll do that'** and **the follow-up.**"

An autonomous background agent + Chrome extension that turns the things
people *say* they'll do in a meeting into tracked obligations that get
chased down automatically — nudged, escalated, cascaded, and reported —
until they're actually done. It runs on Google Meet, Zoom, and Microsoft
Teams, writes everything to Notion in real time, and never requires anyone
to open a dashboard for it to work.

---

## The Problem

Studies on meeting follow-through put the number at **60–70% of verbal
commitments forgotten or unacted-on within 48 hours**. Meeting minutes get
written, filed in a doc nobody reopens, and the "debt" of undone promises
quietly compounds — meeting after meeting, sprint after sprint. Every
existing tool in this space stops at the *minutes*. Nothing actually
**collects** on what was promised.

That's the gap this project fills.

---

## What This Project Actually Is

1. Joins a meeting passively as a **Chrome extension** (Meet / Zoom / Teams)
2. Reads **live captions straight from the page DOM** — zero audio/video
   processing, no bot avatar in the call, nothing recorded
3. Optionally pre-loads context *before* the meeting starts (a pre-brief —
   "here's what's still open from last time")
4. Runs a full autonomous pipeline in the background: extraction → deadline
   resolution → duplicate/renegotiation detection → agenda tracking
5. Writes every meeting, commitment, person, and agenda slot **live into
   Notion** — 4 auto-created databases, no manual setup
6. Keeps watching after the call ends: nudges via WhatsApp/Slack as
   deadlines approach, escalates if ignored, cascades the delay to anything
   downstream if a deadline is missed
7. Requires nobody to check a dashboard for any of this to happen — the
   dashboard exists only for manual testing without a live call

---

## USPs — Why This Isn't Just Another Meeting Notes Tool

Tools like Otter.ai, Fireflies.ai, Fathom, tl;dv, and Notion AI meeting
notes all do a version of the same thing: **transcribe the call, summarize
it, maybe extract a flat list of action items.** Then they stop. A human
still has to read the notes, remember who owes what, and chase people
manually. That's where every one of them hands the problem back to you.

This project starts exactly where those tools stop:

- **It's a collector, not a note-taker.** The core loop isn't "summarize
  the meeting" — it's "track every promise until it's closed or explicitly
  renegotiated." Nudge → escalate → miss → cascade → reassign is a state
  machine that runs on its own clock, with no human required to trigger it.
- **Zero audio pipeline.** No speech-to-text model, no bot joining as a
  visible participant, no raw audio stored anywhere. It reads the
  captions the platform already renders in the DOM — lighter-weight and
  more privacy-respecting than anything that ingests audio/video.
- **Cross-meeting memory, not per-meeting amnesia.** Most tools treat every
  call as an island. This one generates a "since we last spoke" pre-brief
  before the meeting even starts, surfacing who still owes what and who's
  promised the same thing twice without delivering.
- **Dependency-aware cascading.** Real action-item lists are flat. Here,
  commitments can depend on each other — if an upstream task slips, every
  downstream task's deadline shifts automatically and everyone affected is
  notified, recursively, with no manual re-triaging.
- **One similarity engine, three judgment calls.** A single
  embedding-based classifier (sentence-transformers, cosine similarity)
  decides in real time whether a new commitment is brand new, a duplicate
  of an existing one, a renegotiation ("push that to next week"), or a
  **recommitment of something already missed once** — which gets flagged
  specifically, because a second broken promise is a different signal than
  a first one.
- **Ownerless-commitment catcher.** "We'll handle deployment" / "someone
  should look into this" — vague team-owned commitments that normally die
  silently — trigger an immediate alert asking the meeting owner to name a
  person, instead of quietly falling off a list.
- **Coaching, never blame.** The per-person pattern report is generated
  with explicit instructions to never say "missed" or "failed" — it says
  "renegotiated," frames overload constructively, and always highlights
  who has perfect follow-through. It's a private page for team leads, not
  a public scoreboard.
- **Meeting-level debt score, not just people-level.** The system also
  scores *meetings themselves* — a recurring meeting with chronically low
  follow-through gets flagged with a "consider going async" suggestion,
  something no per-person action-item tracker does.
- **Notion-native, dashboard-optional.** There is no separate app teams
  have to learn or check. Everything lands in Notion, which most teams
  already live in — the dashboard in this repo exists purely for
  transcript-only testing without a live call.
- **Built to be demoed without waiting real days.** A simulated agent
  clock lets the entire nudge → escalate → miss → cascade lifecycle be
  proven end-to-end in minutes instead of waiting for real deadlines to
  arrive.

---

## How It Works

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

---

## Features

- **Commitment extraction** — pulls genuine commitments out of raw meeting
  speech, skipping vague aspirations ("we should look into caching
  sometime"), and separates self-commitments from assignments and
  meeting-request proposals.
- **Deadline resolution** — turns "by Thursday," "before the client call,"
  "end of week," or "ASAP" into real ISO timestamps, using calendar
  context when available.
- **Autonomous watch loop** — nudges at T-24h, escalates at T-6h, marks
  missed after the deadline, all on a background scheduler — no human has
  to check anything for this to run, including through configurable quiet
  hours.
- **Personalized nudges** — a fast LLM writes a warm, human-sounding
  reminder that quotes the person's own words back to them, never a
  robotic "ALERT" message.
- **Live agenda coverage** — per meeting-type templates (Sprint Review,
  Project Kickoff, Event Planning, Club Meeting) track whether required
  topics were actually discussed, and fire a wrap-up warning before the
  meeting ends if something required is still missing.
- **Meeting minutes generation** — a clean, structured MoM (summary, key
  decisions, action-item table, ownerless items, missed agenda items, next
  meeting) is auto-generated the moment a meeting ends.
- **Cross-meeting pre-briefs** — before a new meeting even starts, the
  agent can generate a "since we last spoke" briefing: what's still open,
  what's overdue, who's promised the same thing twice.
- **Notion-first reporting** — every meeting, commitment, person, and
  agenda slot is mirrored live into 4 auto-created Notion databases, with
  verbatim-quote provenance blocks and timestamped activity logs.
- **Cascading delay propagation** — when a commitment is missed or its
  deadline is pushed, the delay automatically propagates (recursively) to
  everything that depends on it, notifying every affected owner.
- **Ownerless-commitment alerts** — "we'll handle it" / "someone should"
  style commitments get flagged and pushed to the meeting owner
  immediately instead of silently falling through.
- **Recommitment & duplicate detection** — one embedding-based similarity
  engine classifies every new commitment as new, a duplicate merge, a
  renegotiation, or a flagged recommit of something already missed.
- **Overcommitment & reassignment suggestions** — when someone's open-item
  count outpaces their historical completion rate, the agent flags it and
  suggests a specific, capacity-available teammate to reassign to.
- **Confidence-gated review queue** — low-confidence extractions are
  routed to a review state instead of silently entering the pipeline as
  fact.
- **Per-person and per-meeting debt scoring** — coaching-toned pattern
  reports for team leads, plus a meeting-level follow-through score that
  flags chronically unproductive recurring meetings.
- **Google Calendar integration** — reads upcoming events to resolve
  implicit deadlines and can draft (human-confirmed) follow-up meetings.
- **WhatsApp + Slack delivery with fallback** — nudges and escalations go
  out over WhatsApp (Twilio) with automatic Slack fallback if unavailable.
- **Mock mode & simulated clock** — the entire pipeline runs end-to-end on
  canned responses with zero external API calls, and a `/simulate`
  endpoint fast-forwards the agent's clock so the full nudge → escalate →
  miss → cascade lifecycle can be demoed in minutes.
- **Multi-platform capture, one shared core** — a single caption-parsing
  engine (`content_common.js`) drives platform-specific selector modules
  for Meet, Zoom, and Teams, plus a browser dashboard for transcript-only
  testing when there's no live call to join.

---

## Tech Stack

- **LLM:** [Featherless AI](https://featherless.ai) (OpenAI-compatible) —
  a 70B model (`Meta-Llama-3.1-70B-Instruct`) for extraction, resolution,
  and reports; a fast 8B model (`Llama-3.1-8B-Instruct`) for nudge text
- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` — real
  cosine-similarity matching for duplicate/renegotiation/recommit
  detection, robust to paraphrasing across meetings
- **Backend:** FastAPI + SQLite (single-file ledger, source of truth for
  the watch loop)
- **Live capture:** Chrome extension (Manifest V3) reading captions
  straight from the Google Meet / Zoom / Teams DOM — or paste a
  transcript into the dashboard
- **Notifications:** Slack Incoming Webhook, WhatsApp via Twilio
- **Reporting:** Notion API — 4 databases (Meetings, Commitments, People,
  Agenda Coverage) auto-created on first run
- **Calendar:** Google Calendar API (OAuth, one-time interactive setup)
- **Scheduler:** APScheduler, driven by a simulated agent clock for
  demoability without waiting on real time

---

## Project Structure

```
meeting-debt-collector/
├── agent/                 FastAPI backend — extraction, resolution, scheduler,
│                          similarity engine, Notion reporter, calendar agent
├── extension/             Chrome extension (Manifest V3) — Meet/Zoom/Teams
├── frontend/              Manual-testing dashboard (no live meeting needed)
├── docs/                  Demo script and supporting docs
└── requirements.txt
```

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
ones), and process it the same way the extension would — useful for
testing without joining an actual call.

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

See `docs/demo_script.md` for a full 4-minute walkthrough script covering
extraction, live agenda coverage, the clock trick, and the coaching report.

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

---

## Future Scope

- **Cross-platform commitment consolidation** — extend ingestion beyond
  meetings to Slack threads and email, feeding the same extraction and
  ledger schema, so "I'll send that doc" in a DM is tracked exactly like a
  spoken commitment.
- **Skill-based reassignment matching** — tag people with skills in
  `person_stats` so overload-driven reassignment suggestions match on
  actual capability, not just spare capacity.
- **Click-to-audio provenance** — `timestamp_sec` is already stored per
  commitment; wire up an `<audio>`/video scrubber so a commitment page
  jumps straight to the moment it was said.
- **Alternative delivery sinks** — push commitments into Jira, Linear, or
  Asana as an option alongside (or instead of) Notion, for teams whose
  source of truth lives elsewhere.
- **Confirm-by-reply** — let a person mark a commitment done by simply
  replying "done" to the WhatsApp/Slack nudge, closing the loop without a
  dashboard visit or a curl command.
- **Auto-confirmed follow-up scheduling** — evolve the existing
  human-confirmed calendar drafts into a one-tap "yes, book it" flow.
- **Local/fine-tuned extraction model** — reduce dependence on an external
  LLM API for latency, cost, and offline/air-gapped use cases.
- **Multi-language caption support** — extend the extraction and
  resolution prompts to non-English transcripts as captioning support
  broadens on each platform.
- **Longitudinal analytics** — trend views over weeks/quarters (team
  follow-through drift, meeting debt trending up or down) beyond the
  point-in-time pattern report.

---

## Team
Built by the project owner with Claude Code, from a hand-written build
specification (`complete-agent-buildspec-final.md`).
