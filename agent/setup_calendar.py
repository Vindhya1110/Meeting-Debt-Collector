"""
One-time interactive Google Calendar setup.

Run this manually from the agent/ directory once:
    python setup_calendar.py

It opens a browser for OAuth consent and saves token.json. After that,
the running server can read calendar events without ever needing a browser.
"""
from calendar_agent import _get_service

if __name__ == "__main__":
    service = _get_service(interactive=True)
    if service is None:
        print("Calendar setup failed — check credentials.json is present in agent/.")
    else:
        print("Calendar connected. token.json saved. The server can now use real calendar context.")
