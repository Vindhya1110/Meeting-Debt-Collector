import os
import json
import requests
from groq import Groq
from prompts import NUDGE_GENERATION_PROMPT, REASSIGNMENT_SUGGESTION_PROMPT
from mock_responses import MOCK_NUDGE_TEXT

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
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

    try:
        response = groq_client.chat.completions.create(
            model=MODEL,
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
    except Exception as e:
        print(f"Nudge generation failed, using fallback message: {e}")
        return (
            f"Hey {commitment['owner']} — following up on \"{commitment['commitment_text']}\". "
            f"That's due soon. Want to give a quick status update?"
        )

def send_nudge(commitment: dict, hours_until: float):
    """Send personalized nudge via WhatsApp -> Slack fallback."""
    message = _generate_message(commitment, hours_until)

    # Try WhatsApp first (most impressive on demo day)
    if TWILIO_SID and WA_TO and not MOCK_MODE:
        try:
            from twilio.rest import Client
            twilio = Client(TWILIO_SID, TWILIO_TOKEN)
            twilio.messages.create(
                body=f"\U0001F514 {message}",
                from_=WA_FROM,
                to=WA_TO
            )
            print(f"WhatsApp nudge sent to {WA_TO}")
            return
        except Exception as e:
            print(f"WhatsApp failed, falling back to Slack: {e}")

    # Slack fallback
    if SLACK_WEBHOOK and not MOCK_MODE:
        payload = {
            "text": f"*Nudge for {commitment['owner']}*\n{message}",
            "attachments": [{
                "color": "#FFA500",
                "text": f"Task: {commitment['normalized_task']}\nDeadline: {commitment['deadline']}"
            }]
        }
        try:
            r = requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
            print(f"Slack nudge for {commitment['owner']} -> {r.status_code}")
        except Exception as e:
            print(f"Slack nudge failed (non-fatal): {e}")

def send_escalation(commitment: dict):
    """Escalate to meeting owner — different message, wider visibility."""
    message = (
        f"⚠️ *Escalation Alert*\n"
        f"{commitment['owner']} committed to: _{commitment['normalized_task']}_\n"
        f"Deadline passed without completion. "
        f"Original commitment: \"{commitment['commitment_text']}\"\n"
        f"Recommend: reassign or schedule a quick sync."
    )
    if SLACK_WEBHOOK and not MOCK_MODE:
        try:
            r = requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
            print(f"Slack escalation for {commitment['owner']} -> {r.status_code}")
        except Exception as e:
            print(f"Slack escalation failed (non-fatal): {e}")

def send_ownerless_alert(commitment: dict, meeting_owner: str):
    """Alert meeting owner when an ownerless commitment is detected."""
    message = (
        f"⚠️ *Ownerless Commitment Detected*\n"
        f"In this transcript: \"{commitment.get('commitment_text', '')}\"\n"
        f"Nobody has been assigned. Who's taking this?\n"
        f"Reply with a name or assign from the dashboard."
    )
    if SLACK_WEBHOOK and not MOCK_MODE:
        try:
            requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
        except Exception as e:
            print(f"Slack ownerless alert failed (non-fatal): {e}")

def send_reassignment_suggestion(commitment: dict, open_count: int, weekly_capacity: float):
    """U7: Proactively suggest redistribution when someone is overloaded."""
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

    try:
        response = groq_client.chat.completions.create(
            model=MODEL,
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
    except Exception as e:
        print(f"Reassignment suggestion generation failed: {e}")
        suggestion = f"Consider reassigning '{commitment['normalized_task']}' from {commitment['owner']} to {available[0]['person']}, who has spare capacity."

    message = f"\U0001F4A1 *Redistribution Suggestion*\n{suggestion}"

    if SLACK_WEBHOOK and not MOCK_MODE:
        try:
            requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
        except Exception as e:
            print(f"Slack reassignment suggestion failed (non-fatal): {e}")

def send_beneficiary_notification(commitment: dict):
    """U10: Notify the person who was waiting when a task is marked done."""
    if not commitment.get("beneficiary"):
        return
    message = (
        f"✅ {commitment['owner']} completed: _{commitment['normalized_task']}_\n"
        f"You were waiting on this. It's done!"
    )
    if SLACK_WEBHOOK and not MOCK_MODE:
        try:
            requests.post(SLACK_WEBHOOK, json={
                "text": f"*For {commitment['beneficiary']}*: {message}"
            }, timeout=5)
        except Exception as e:
            print(f"Slack beneficiary notification failed (non-fatal): {e}")
