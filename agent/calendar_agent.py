"""
Google Calendar integration.

APPROVAL FLOW (mandatory — never bypass):
  1. scheduler.py detects missed/at-risk commitment
  2. calls propose_and_ask_slack(commitment)
       → creates a calendar_draft row in SQLite
       → posts Slack message with a /calendar/{draft_id}/confirm link
  3. Human clicks the link / runs the curl command
  4. main.py /calendar/{draft_id}/confirm calls confirm_event(draft_id)
       → ONLY THEN creates the Google Calendar event
       → Posts the Meet link back to Slack

An agent that silently books time on someone's calendar is unacceptable.
"""

import os, json, uuid, requests
from datetime import datetime, timedelta
from models import get_db, log_event

CREDS_PATH = os.getenv("GOOGLE_CALENDAR_CREDS", "agent/credentials.json")
TOKEN_PATH = "agent/token.json"
SCOPES     = ["https://www.googleapis.com/auth/calendar"]
SLACK      = os.getenv("SLACK_WEBHOOK_URL", "")
AGENT_URL  = f"http://localhost:{os.getenv('AGENT_PORT', '8000')}"


# ── Google Auth ───────────────────────────────────────────────────────────────

def _get_service():
    """Get authenticated Google Calendar service. Opens browser on first run."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                print("[Calendar] credentials.json not found — skipping calendar setup")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_upcoming_events(days: int = 7) -> list:
    """
    Fetch calendar events for deadline resolution context.
    Returns list of {title, datetime} for the resolver.
    Falls back to [] if calendar not configured.
    """
    try:
        svc = _get_service()
        if not svc:
            return []
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        result = svc.events().list(
            calendarId="primary", timeMin=now, timeMax=end,
            maxResults=20, singleEvents=True, orderBy="startTime"
        ).execute()
        return [
            {
                "title":    e.get("summary", ""),
                "datetime": e["start"].get("dateTime", e["start"].get("date", "")),
            }
            for e in result.get("items", [])
        ]
    except Exception as e:
        print(f"[Calendar] fetch failed (using demo calendar): {e}")
        return []


# ── Step 1: Propose → Slack (called by scheduler, never creates the event) ───

def propose_and_ask_slack(commitment: dict) -> str:
    """
    Creates a draft calendar event row in SQLite.
    Posts a Slack message asking for approval.
    Returns the draft_id.

    The event is NOT created yet. Human must approve.
    """
    draft_id = str(uuid.uuid4())
    now      = datetime.utcnow()

    # Suggest a time: next business day at 10 AM
    suggested = _next_business_day_10am(now)

    # Save draft to SQLite
    conn = get_db()
    conn.execute(
        "INSERT INTO calendar_drafts "
        "(id, commitment_id, summary, start_iso, duration_min, attendees, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (
            draft_id,
            commitment["id"],
            f"Quick sync: {commitment.get('normalized_task', 'follow-up')}",
            suggested.isoformat(),
            15,
            json.dumps([commitment.get("owner", "Unknown")]),
            now.isoformat(),
        )
    )
    conn.commit()
    conn.close()

    # Log the proposal
    log_event(commitment["id"], "calendar_proposed", draft_id)

    # Post Slack approval message
    _post_approval_to_slack(draft_id, commitment, suggested)

    return draft_id


def _post_approval_to_slack(draft_id: str, commitment: dict, suggested: datetime):
    """
    Post a Slack message asking the human to approve or deny the calendar event.
    Includes the approve curl command so they can act without a UI.
    """
    if not SLACK:
        print(f"[Calendar] No Slack webhook — draft {draft_id[:8]} pending approval")
        return

    owner    = commitment.get("owner", "Unknown")
    task     = commitment.get("normalized_task", "follow-up")
    verbatim = commitment.get("commitment_text", "")
    time_str = suggested.strftime("%A %b %d at %-I:%M %p")

    approve_url = f"{AGENT_URL}/calendar/{draft_id}/confirm"

    message = {
        "text": f"📅 *Calendar Event Proposed — Approval Required*",
        "attachments": [
            {
                "color":  "#FFA500",
                "fields": [
                    {"title": "For",      "value": owner,    "short": True},
                    {"title": "Topic",    "value": task,     "short": True},
                    {"title": "Proposed", "value": time_str, "short": True},
                    {"title": "Duration", "value": "15 min", "short": True},
                    {
                        "title": "Original commitment",
                        "value": f'"{verbatim}"',
                        "short": False,
                    },
                ],
            },
            {
                "color": "#1D9E75",
                "text": (
                    f"*To approve and create the Google Calendar event + Meet link:*\n"
                    f"```\n"
                    f"curl -X POST {approve_url}\n"
                    f"     -H 'Content-Type: application/json'\n"
                    f"     -d '{{\"attendee_emails\": [\"owner@email.com\"]}}'\n"
                    f"```\n"
                    f"Or click: <{approve_url}|Approve in browser>\n\n"
                    f"*To deny:* No action needed — draft expires in 48h."
                ),
            },
        ],
    }

    try:
        requests.post(SLACK, json=message, timeout=5)
        print(f"[Calendar] Approval request sent to Slack for draft {draft_id[:8]}")
    except Exception as e:
        print(f"[Calendar] Slack post failed: {e}")


# ── Step 2: Confirm → Create event (called ONLY from /calendar/{id}/confirm) ─

def confirm_event(draft_id: str, attendee_emails: list) -> dict:
    """
    Called ONLY after human explicitly approves via Slack.
    Creates the Google Calendar event and returns the Meet link.
    Updates draft status to 'created' in SQLite.
    """
    conn  = get_db()
    draft = conn.execute(
        "SELECT * FROM calendar_drafts WHERE id=?", (draft_id,)
    ).fetchone()
    conn.close()

    if not draft:
        return {"ok": False, "error": "Draft not found"}

    draft = dict(draft)

    if draft["status"] == "created":
        return {"ok": False, "error": "Event already created"}

    meet_link = ""
    event_url = ""

    try:
        svc = _get_service()
        if not svc:
            raise Exception("Google Calendar not configured")

        start = datetime.fromisoformat(draft["start_iso"])
        end   = start + timedelta(minutes=draft["duration_min"])

        event = {
            "summary":     draft["summary"],
            "description": f"Auto-proposed by Meeting Debt Collector\n"
                           f"Commitment ID: {draft['commitment_id']}",
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end":   {"dateTime": end.isoformat(),   "timeZone": "Asia/Kolkata"},
            "attendees": [{"email": e} for e in attendee_emails if "@" in e],
            "conferenceData": {
                "createRequest": {
                    "requestId":             f"mdc-{draft_id[:8]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        result = svc.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        meet_link = result.get("hangoutLink", "")
        event_url = result.get("htmlLink", "")

        print(f"[Calendar] Event created: {event_url}")

    except Exception as e:
        print(f"[Calendar] Event creation failed: {e}")
        # Post failure to Slack
        _post_to_slack(
            f"❌ *Calendar event creation failed*\n"
            f"Draft: `{draft_id[:8]}`\nError: {e}"
        )
        return {"ok": False, "error": str(e)}

    # Update SQLite
    conn = get_db()
    conn.execute(
        "UPDATE calendar_drafts SET status='created' WHERE id=?", (draft_id,)
    )
    conn.commit()
    conn.close()
    log_event(draft["commitment_id"], "calendar_created", event_url)

    # Post success to Slack
    _post_to_slack(
        f"✅ *Calendar event created*\n"
        f"*{draft['summary']}*\n"
        f"🔗 Meet link: {meet_link or 'Check your calendar'}\n"
        f"📅 Event: {event_url}"
    )

    return {
        "ok":        True,
        "meet_link": meet_link,
        "event_url": event_url,
        "draft_id":  draft_id,
    }


# ── /calendar/{id}/confirm routes ─────────────────────────────────────────────
# Registered in agent/main.py: POST/GET /calendar/{draft_id}/confirm,
# calling confirm_event() below. Kept out of this file so calendar_agent.py
# has no dependency on FastAPI/the app object.


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_business_day_10am(from_dt: datetime) -> datetime:
    """Returns next weekday at 10 AM from the given datetime."""
    d = from_dt + timedelta(days=1)
    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d += timedelta(days=1)
    return d.replace(hour=10, minute=0, second=0, microsecond=0)


def _post_to_slack(text: str):
    if not SLACK:
        return
    try:
        requests.post(SLACK, json={"text": text}, timeout=5)
    except Exception as e:
        print(f"[Calendar] Slack post failed: {e}")


        