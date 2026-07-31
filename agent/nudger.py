import os
import requests
from llm import call_fast
from prompts import NUDGE_PROMPT, REASSIGNMENT_PROMPT
from models import get_db
from mock_mode import MOCK_NUDGE_TEXT
from notion_reporter import update_commitment_status

SLACK = os.getenv("SLACK_WEBHOOK_URL", "")
WA_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
WA_TO = os.getenv("TWILIO_WHATSAPP_TO", "")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

def _gen_nudge(c: dict, hours_until: float) -> str:
    if MOCK:
        return MOCK_NUDGE_TEXT
    try:
        return call_fast(
            system="You write friendly nudge messages from colleagues.",
            user=NUDGE_PROMPT.format(
                owner=c["owner"],
                commitment_text=c["commitment_text"],
                meeting_title=c.get("meeting_title", "your meeting"),
                deadline=c.get("deadline", ""),
                hours_until=round(hours_until, 1)
            ),
            temperature=0.7,
            max_tokens=150,
            expect_json=False,
            provider="groq"
        )
    except Exception as e:
        print(f"[Nudger] message generation failed, using fallback: {e}")
        return (f"Hey {c['owner']} — following up on \"{c['commitment_text']}\". "
                f"That's due soon. Want to give a quick status update?")

def _whatsapp(text: str) -> bool:
    if not WA_TO or not TWILIO_SID or MOCK:
        return False
    try:
        from twilio.rest import Client as Twilio
        Twilio(TWILIO_SID, TWILIO_TOKEN).messages.create(
            body=f"\U0001F514 {text}", from_=WA_FROM, to=WA_TO)
        print("[WhatsApp] sent")
        return True
    except Exception as e:
        print(f"[WhatsApp] failed, falling back to Slack: {e}")
        return False

def _slack(text: str, color: str = "#FFA500"):
    if not SLACK or MOCK:
        return
    try:
        r = requests.post(SLACK, json={"attachments": [{"color": color, "text": text}]}, timeout=4)
        print(f"[Slack] -> {r.status_code}")
    except Exception as e:
        print(f"[Slack] failed (non-fatal): {e}")

def _deliver(text: str, color: str = "#FFA500"):
    if not _whatsapp(text):
        _slack(text, color)

def send_nudge(c: dict, hours_until: float):
    msg = _gen_nudge(c, hours_until)
    _deliver(msg)
    update_commitment_status(
        c.get("notion_page_id", ""), "nudged", c.get("nudge_count", 0) + 1,
        f"Nudge sent at T-{hours_until:.1f}h: {msg[:200]}"
    )

def send_escalation(c: dict):
    text = (f"⚠️ *Escalation* — {c['owner']} committed to "
            f"_{c.get('normalized_task', '?')}_ and the deadline has passed.\n"
            f"Original: \"{c.get('commitment_text', '')}\"")
    _deliver(text, "#E24B4A")
    update_commitment_status(c.get("notion_page_id", ""), "escalated",
                              detail="Escalated to meeting owner")

def send_ownerless_alert(c: dict, meeting_owner: str):
    _slack(f"⚠️ *Ownerless Commitment Detected*\n"
           f"\"{c.get('commitment_text', '')}\"\n"
           f"No owner assigned. {meeting_owner}, who's taking this?\n"
           f"POST /commitments/{c['id']}/action {{\"action\":\"assign_owner\","
           f"\"new_owner\":\"Name\"}}", "#FFA500")

def send_wrapup_alert(meeting_id: str, missed_slots: list):
    labels = ", ".join(s["label"] for s in missed_slots)
    _slack(f"📋 *Wrap-up Alert* (meeting `{meeting_id[:8]}`)\n"
           f"Before you close — required items not covered: {labels}", "#FFA500")

def send_cascade(c: dict, delay_h: float, upstream: str):
    _slack(f"🔗 *Cascade Shift* — {c['owner']}'s task "
           f"_{c.get('normalized_task', '?')}_ shifted by {delay_h:.0f}h "
           f"because upstream task '{upstream}' slipped.", "#BA7517")

def send_recommit_warning(c: dict, warning: str):
    _slack(f"🔁 *Recommitment Detected*\n{warning}\n"
           f"Task: _{c.get('normalized_task', '?')}_", "#534AB7")

def send_beneficiary_done(c: dict):
    if not c.get("beneficiary"):
        return
    _slack(f"✅ *For {c['beneficiary']}*: "
           f"{c['owner']} completed _{c.get('normalized_task', '?')}_. Done!")
    update_commitment_status(c.get("notion_page_id", ""), "done",
                              detail="Marked done - beneficiary notified")

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
    if not avail:
        return

    try:
        msg = call_fast(
            system="You suggest task reassignments concisely.",
            user=REASSIGNMENT_PROMPT.format(
                owner=c["owner"], open_count=open_count, rate=rate,
                available_json=[dict(a) for a in avail],
                task=c.get("normalized_task", "?")
            ),
            expect_json=False,
            provider="groq"
        )
    except Exception as e:
        print(f"[Nudger] reassignment suggestion failed: {e}")
        msg = f"Consider reassigning '{c.get('normalized_task','?')}' from {c['owner']} to {avail[0]['person']}, who has spare capacity."

    _slack(f"💡 *Redistribution Suggestion*\n{msg}", "#0F6E56")
