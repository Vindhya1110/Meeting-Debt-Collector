"""
ALL Notion output lives here.
Creates and maintains 4 Notion databases under one parent page:
  1. Meetings          — one page per meeting, with MoM embedded
  2. Commitments       — one page per commitment, live status
  3. People            — per-person stats and coaching summary
  4. Agenda Coverage   — per-meeting agenda checklist

Every write is fire-and-forget (non-fatal if it fails).
"""
import os
import requests
from datetime import datetime
from models import get_db, get_notion_id, set_notion_id

TOKEN = os.getenv("NOTION_TOKEN", "")
PARENT = os.getenv("NOTION_PARENT_PAGE_ID", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ── Database IDs (stored in SQLite after first-run creation) ──────────────────

def _db(key):
    env_map = {
        "meetings": "NOTION_MEETINGS_DB_ID",
        "commitments": "NOTION_COMMITMENTS_DB_ID",
        "people": "NOTION_PEOPLE_DB_ID",
        "agenda": "NOTION_AGENDA_DB_ID",
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
            print(f"[Notion] {path} -> {r.status_code}: {r.text[:300]}")
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
        if r.status_code != 200:
            print(f"[Notion] patch {path} -> {r.status_code}: {r.text[:300]}")
            return None
        return r.json()
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
        print("[Notion] No token/parent page configured - skipping setup")
        return

    _ensure_db("meetings", {
        "Name": {"title": {}},
        "Type": {"select": {}},
        "Platform": {"select": {}},
        "Date": {"date": {}},
        "Owner": {"rich_text": {}},
        "Status": {"select": {"options": [
            {"name": "active", "color": "blue"},
            {"name": "finalized", "color": "green"},
        ]}},
        "Commitments": {"number": {}},
        "Follow Through": {"number": {}},
    })

    _ensure_db("commitments", {
        "Task": {"title": {}},
        "Owner": {"select": {}},
        "Deadline": {"date": {}},
        "Status": {"select": {"options": [
            {"name": "open", "color": "blue"},
            {"name": "nudged", "color": "yellow"},
            {"name": "escalated", "color": "orange"},
            {"name": "done", "color": "green"},
            {"name": "missed", "color": "red"},
            {"name": "renegotiated", "color": "purple"},
            {"name": "reassigned", "color": "gray"},
            {"name": "review", "color": "pink"},
        ]}},
        "Confidence": {"select": {"options": [
            {"name": "high", "color": "green"},
            {"name": "medium", "color": "yellow"},
            {"name": "low", "color": "red"},
        ]}},
        "Meeting": {"rich_text": {}},
        "Verbatim": {"rich_text": {}},
        "Depends On": {"rich_text": {}},
        "Beneficiary": {"rich_text": {}},
        "Owner Type": {"select": {"options": [
            {"name": "person", "color": "blue"},
            {"name": "ownerless", "color": "orange"},
        ]}},
        "Nudges Sent": {"number": {}},
        "Warning": {"rich_text": {}},
    })

    _ensure_db("people", {
        "Name": {"title": {}},
        "Committed": {"number": {}},
        "On Time": {"number": {}},
        "Renegotiated": {"number": {}},
        "Missed": {"number": {}},
        "Follow Through %": {"number": {}},
        "Weekly Capacity": {"number": {}},
        "At Risk": {"checkbox": {}},
        "Coaching Note": {"rich_text": {}},
    })

    _ensure_db("agenda", {
        "Slot": {"title": {}},
        "Meeting": {"rich_text": {}},
        "Required": {"checkbox": {}},
        "Status": {"select": {"options": [
            {"name": "pending", "color": "gray"},
            {"name": "covered", "color": "green"},
            {"name": "missed", "color": "red"},
        ]}},
        "Evidence": {"rich_text": {}},
    })

    print("[Notion] Workspace setup complete")

def _ensure_db(name: str, properties: dict):
    existing = _db(name)
    if existing:
        print(f"[Notion] {name} DB already exists: {existing[:8]}...")
        return existing

    result = _post("databases", {
        "parent": {"type": "page_id", "page_id": PARENT},
        "title": [{"type": "text", "text": {"content": f"MDC - {name.title()}"}}],
        "properties": properties
    })
    if result:
        db_id = result["id"]
        set_notion_id(f"notion_db_{name}", db_id)
        print(f"[Notion] Created {name} database: {db_id[:8]}...")
        return db_id
    print(f"[Notion] Failed to create {name} database - is the parent page "
          f"shared with the integration? (••• -> Connections -> add your integration)")
    return None

# ── Meeting pages ─────────────────────────────────────────────────────────────

def create_meeting_page(meeting: dict) -> str:
    """Create a Notion page for a new meeting. Returns page ID."""
    db = _db("meetings")
    if not db:
        return ""

    result = _post("pages", {
        "parent": {"database_id": db},
        "properties": {
            "Name": {"title": [{"text": {"content": meeting.get("title", "Untitled")}}]},
            "Type": {"select": {"name": meeting.get("type", "club_meeting")}},
            "Platform": {"select": {"name": meeting.get("platform", "unknown")}},
            "Date": {"date": {"start": meeting.get("date", datetime.utcnow().isoformat())}},
            "Owner": {"rich_text": [{"text": {"content": meeting.get("owner", "")}}]},
            "Status": {"select": {"name": "active"}},
            "Commitments": {"number": 0},
        }
    })
    return result["id"] if result else ""

def update_meeting_page(page_id: str, updates: dict):
    """Update meeting page properties and optionally append MoM as page content."""
    if not page_id:
        return

    props = {}
    if "status" in updates:
        props["Status"] = {"select": {"name": updates["status"]}}
    if "commitments_count" in updates:
        props["Commitments"] = {"number": updates["commitments_count"]}
    if "follow_through" in updates:
        props["Follow Through"] = {"number": updates["follow_through"]}

    if props:
        _patch(f"pages/{page_id}", {"properties": props})

    if "mom" in updates and updates["mom"]:
        _post(f"blocks/{page_id}/children", {
            "children": [
                {"object": "block", "type": "heading_2",
                 "heading_2": {"rich_text": [{"text": {"content": "Minutes of Meeting"}}]}},
                *[
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}}
                    for line in updates["mom"].split("\n")[:100]
                    if line.strip()
                ]
            ]
        })

    if "agenda" in updates:
        slots = updates["agenda"].get("slots", [])
        if slots:
            rows = [{"object": "block", "type": "heading_3",
                     "heading_3": {"rich_text": [{"text": {"content": "Agenda Coverage"}}]}}]
            for s in slots:
                icon = "✅" if s["status"] == "covered" else "❌" if s["required"] else "⬜"
                rows.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [
                        {"text": {"content": f"{icon} {s['label']} - {s['status']}"}}
                    ]}
                })
            _post(f"blocks/{page_id}/children", {"children": rows[:50]})

# ── Commitment pages ──────────────────────────────────────────────────────────

def create_commitment_page(c: dict, meeting_title: str) -> str:
    """Create a Notion page for a commitment. Returns page ID."""
    db = _db("commitments")
    if not db:
        return ""

    conf = c.get("confidence", 0.9)
    conf_label = "high" if conf >= 0.8 else "medium" if conf >= 0.5 else "low"

    props = {
        "Task": {"title": [{"text": {"content": c.get("normalized_task", "?")[:2000]}}]},
        "Owner": {"select": {"name": c.get("owner", "Unknown") or "Unknown"}},
        "Status": {"select": {"name": c.get("status", "open")}},
        "Confidence": {"select": {"name": conf_label}},
        "Meeting": {"rich_text": [{"text": {"content": meeting_title}}]},
        "Verbatim": {"rich_text": [{"text": {"content": c.get("commitment_text", "")[:2000]}}]},
        "Depends On": {"rich_text": [{"text": {"content": c.get("depends_on", "") or ""}}]},
        "Beneficiary": {"rich_text": [{"text": {"content": c.get("beneficiary", "") or ""}}]},
        "Owner Type": {"select": {"name": c.get("owner_type", "person")}},
        "Nudges Sent": {"number": 0},
        "Warning": {"rich_text": [{"text": {"content": c.get("warning", "") or ""}}]},
    }
    if c.get("deadline"):
        props["Deadline"] = {"date": {"start": c["deadline"]}}

    result = _post("pages", {"parent": {"database_id": db}, "properties": props})
    page_id = result["id"] if result else ""

    if page_id and c.get("commitment_text"):
        _post(f"blocks/{page_id}/children", {"children": [
            {"object": "block", "type": "quote",
             "quote": {"rich_text": [{"text": {"content":
                 f"\"{c['commitment_text']}\" - {c.get('speaker', '?')} "
                 f"@ {c.get('timestamp_sec', 0)}s"
             }}]}},
        ]})

    return page_id

def update_commitment_status(page_id: str, status: str,
                              nudge_count: int = None, detail: str = ""):
    """Update a commitment's status in Notion."""
    if not page_id:
        return
    props = {"Status": {"select": {"name": status}}}
    if nudge_count is not None:
        props["Nudges Sent"] = {"number": nudge_count}
    _patch(f"pages/{page_id}", {"properties": props})
    if detail:
        _post(f"blocks/{page_id}/children", {"children": [
            {"object": "block", "type": "callout",
             "callout": {"rich_text": [{"text": {"content":
                 f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] {detail[:1900]}"
             }}], "icon": {"emoji": "\U0001F4CC"}}}
        ]})

# ── People / pattern report ───────────────────────────────────────────────────

def upsert_person_page(stats: dict, coaching_note: str = ""):
    """Create or update a person's page in the People database."""
    db = _db("people")
    if not db:
        return

    total = stats.get("committed", 0) or 1
    follow_through = round(stats.get("on_time", 0) / total * 100, 1)
    at_risk = follow_through < 50 and stats.get("committed", 0) >= 3

    existing_id = stats.get("notion_page_id", "")

    props = {
        "Name": {"title": [{"text": {"content": stats["person"]}}]},
        "Committed": {"number": stats.get("committed", 0)},
        "On Time": {"number": stats.get("on_time", 0)},
        "Renegotiated": {"number": stats.get("renegotiated", 0)},
        "Missed": {"number": stats.get("missed", 0)},
        "Follow Through %": {"number": follow_through},
        "Weekly Capacity": {"number": stats.get("avg_completion_per_week", 2.0)},
        "At Risk": {"checkbox": at_risk},
        "Coaching Note": {"rich_text": [{"text": {"content": coaching_note[:2000]}}]},
    }

    if existing_id:
        _patch(f"pages/{existing_id}", {"properties": props})
    else:
        result = _post("pages", {"parent": {"database_id": db}, "properties": props})
        if result:
            conn = get_db()
            conn.execute("UPDATE person_stats SET notion_page_id=? WHERE person=?",
                         (result["id"], stats["person"]))
            conn.commit()
            conn.close()

def create_pattern_report_page(summary: str, stats: list, debt_scores: list) -> str:
    """Create a full pattern report page under the parent Notion page."""
    if not PARENT:
        return ""

    result = _post("pages", {
        "parent": {"page_id": PARENT},
        "properties": {
            "title": [{"text": {"content":
                f"Pattern Report - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            }}]
        },
        "children": [
            {"object": "block", "type": "heading_1",
             "heading_1": {"rich_text": [{"text": {"content": "Team Commitment Health Report"}}]}},
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"text": {"content": summary}}]}},
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": [{"text": {"content": "Per-Person Stats"}}]}},
            *[{
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"text": {"content":
                    f"{'⚡' if s.get('at_risk') else '✅'} {s['person']} - "
                    f"{s.get('on_time', 0)}/{s.get('committed', 0)} on time "
                    f"({round(s.get('on_time', 0) / (s.get('committed', 0) or 1) * 100)}%)"
                }}]}
            } for s in stats],
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": [{"text": {"content": "Meeting Debt Scores"}}]}},
            *[{
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"text": {"content":
                    f"{'\U0001F504' if m.get('suggest_async') else '\U0001F4CB'} {m['title']}: "
                    f"{round(m.get('rate', 0) * 100)}% follow-through"
                    f"{' - consider async' if m.get('suggest_async') else ''}"
                }}]}
            } for m in debt_scores[:10]],
        ]
    })
    return result["id"] if result else ""

# ── Agenda ────────────────────────────────────────────────────────────────────

def log_agenda_slot(meeting_id: str, slot: dict):
    """Log an agenda slot's coverage status to Notion."""
    db = _db("agenda")
    if not db:
        return
    _post("pages", {
        "parent": {"database_id": db},
        "properties": {
            "Slot": {"title": [{"text": {"content": slot.get("label", "?")}}]},
            "Meeting": {"rich_text": [{"text": {"content": meeting_id[:8]}}]},
            "Required": {"checkbox": bool(slot.get("required"))},
            "Status": {"select": {"name": slot.get("status", "pending")}},
            "Evidence": {"rich_text": [{"text": {"content":
                (slot.get("evidence_quote", "") or "")[:2000]
            }}]},
        }
    })
