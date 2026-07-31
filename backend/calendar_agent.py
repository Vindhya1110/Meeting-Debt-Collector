import os
from datetime import datetime, timedelta

CREDS_PATH = os.getenv("GOOGLE_CALENDAR_CREDS", "credentials.json")
TOKEN_PATH = "token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

def _get_service(interactive: bool = False):
    """
    Build an authenticated Calendar service.
    interactive=False (default): only uses an existing saved token. Never opens
    a browser. Returns None if no valid token exists yet — callers must treat
    that as "calendar unavailable" and fall back gracefully.
    interactive=True: allowed to run the one-time browser consent flow. Only
    used from the explicit setup script or user-triggered confirm actions.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import os.path

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        except Exception as e:
            print(f"Calendar token refresh failed: {e}")
            creds = None

    if not creds or not creds.valid:
        if not interactive:
            return None
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not os.path.exists(CREDS_PATH):
            print(f"Calendar credentials file not found at {CREDS_PATH}")
            return None
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def get_upcoming_events(days_ahead: int = 7) -> list:
    """Fetch calendar events to provide context for deadline resolution.
    Never triggers interactive auth — returns [] if not yet connected, and
    resolver.py falls back to a demo calendar in that case."""
    try:
        service = _get_service(interactive=False)
        if service is None:
            return []

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
    Returns draft for human confirmation via Slack/dashboard.
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
    Called ONLY after human confirmation (POST /calendar/confirm).
    Creates the actual Google Calendar event with Meet link.
    Allowed to run the interactive OAuth flow since this is an explicit,
    human-initiated action — not a side effect of passive processing.
    Returns the Meet link, or "" if calendar isn't connected.
    """
    try:
        service = _get_service(interactive=True)
        if service is None:
            return ""

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
