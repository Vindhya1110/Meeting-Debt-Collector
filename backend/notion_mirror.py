import os
import requests

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
    if MOCK_MODE or not NOTION_TOKEN or not NOTION_DB_ID:
        return

    confidence_label = (
        "high" if commitment.get("confidence", 0) >= 0.8
        else "medium" if commitment.get("confidence", 0) >= 0.5
        else "low"
    )

    properties = {
        "Owner": {
            "title": [{"text": {"content": commitment.get("owner", "Unknown")}}]
        },
        "Commitment": {
            "rich_text": [{"text": {"content": commitment.get("normalized_task", "")[:2000]}}]
        },
        "Status": {
            "select": {"name": commitment.get("status", "open")}
        },
        "Source Meeting": {
            "rich_text": [{"text": {"content": commitment.get("meeting_id", "")}}]
        },
        "Confidence": {
            "select": {"name": confidence_label}
        },
        "Depends On": {
            "rich_text": [{"text": {"content": commitment.get("depends_on_hint", "") or ""}}]
        }
    }
    if commitment.get("deadline"):
        properties["Deadline"] = {"date": {"start": commitment["deadline"]}}

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": properties
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
