from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import get_db, get_agent_now

QUIET_HOURS_START = 22  # 10 PM
QUIET_HOURS_END = 8     # 8 AM
EXAM_MODE = False        # Toggle via API endpoint

scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(
        run_watch_loop,
        trigger="interval",
        seconds=10,
        id="watch_loop",
        replace_existing=True
    )
    scheduler.start()
    print("Watch loop started - ticking every 10s")

def stop_scheduler():
    scheduler.shutdown()

def run_watch_loop():
    """
    Core autonomous loop. Runs every 10s.
    Reads agent's simulated clock (not real time).
    Makes all decisions deterministically — LLM is NOT called here.
    """
    from nudger import send_nudge, send_escalation

    now = get_agent_now()

    if _is_quiet_hours(now) and not EXAM_MODE:
        return  # Respect quiet hours

    conn = get_db()
    open_items = conn.execute("""
        SELECT c.*, m.title as meeting_title, m.date as meeting_date
        FROM commitments c
        JOIN meetings m ON c.meeting_id = m.id
        WHERE c.status IN ('open', 'nudged', 'escalated')
        AND c.deadline IS NOT NULL AND c.deadline != ''
    """).fetchall()
    conn.close()

    for item in open_items:
        item = dict(item)
        try:
            deadline = datetime.fromisoformat(item["deadline"])
        except (ValueError, TypeError):
            continue

        time_until = deadline - now
        hours_until = time_until.total_seconds() / 3600

        # RULE 1: Nudge at T-24h if still open
        if hours_until <= 24 and item["status"] == "open":
            if not _claim_status(item["id"], "open", "nudged"):
                continue  # another watch-loop invocation already handled this item
            send_nudge(item, hours_until)
            _log_event(item["id"], "nudged", f"Nudge sent at T-{hours_until:.1f}h")

        # RULE 2: Escalate at T-6h if still only nudged
        elif hours_until <= 6 and item["status"] == "nudged":
            if not _claim_status(item["id"], "nudged", "escalated"):
                continue
            send_escalation(item)
            _log_event(item["id"], "escalated", f"Escalated at T-{hours_until:.1f}h")

        # RULE 3: Mark missed if deadline passed
        elif hours_until < 0 and item["status"] in ("open", "nudged", "escalated"):
            if not _claim_status(item["id"], item["status"], "missed"):
                continue
            _log_event(item["id"], "missed", "Deadline passed without completion")
            _update_person_stats(item["owner"], "missed")
            _check_cascade(item["id"], abs(hours_until))

            # Trigger reassignment suggestion if overloaded
            _maybe_suggest_reassignment(item)

def _check_cascade(commitment_id: str, delay_hours: float):
    """
    When a task is missed/renegotiated, propagate delay to dependent tasks.
    This is U3 — cascading delay propagation.
    """
    conn = get_db()
    dependents = conn.execute("""
        SELECT * FROM commitments
        WHERE depends_on = ? AND status IN ('open', 'nudged')
    """, (commitment_id,)).fetchall()
    conn.close()

    for dep in dependents:
        dep = dict(dep)
        if dep.get("deadline"):
            old_deadline = datetime.fromisoformat(dep["deadline"])
            new_deadline = old_deadline + timedelta(hours=delay_hours)
            conn = get_db()
            conn.execute("""
                UPDATE commitments SET deadline=?, status='open', updated_at=?
                WHERE id=?
            """, (new_deadline.isoformat(), datetime.utcnow().isoformat(), dep["id"]))
            conn.commit()
            conn.close()
            _log_event(dep["id"], "cascade_shifted",
                       f"Shifted by {delay_hours:.1f}h due to upstream delay")
            # Recurse for further downstream
            _check_cascade(dep["id"], delay_hours)

def _maybe_suggest_reassignment(item: dict):
    """
    U7 equivalent: If owner has > threshold open items, generate reassignment suggestion.
    Sent as a Slack message to the meeting owner (team lead), not the overloaded person.
    """
    conn = get_db()
    stats = conn.execute(
        "SELECT * FROM person_stats WHERE person=?", (item["owner"],)
    ).fetchone()
    open_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM commitments WHERE owner=? AND status IN ('open','nudged','escalated')",
        (item["owner"],)
    ).fetchone()["cnt"]
    conn.close()

    if not stats:
        return

    threshold = stats["avg_completion_per_week"]
    if threshold and open_count > threshold * 1.5:
        from nudger import send_reassignment_suggestion
        send_reassignment_suggestion(item, open_count, float(threshold))

def _update_status(commitment_id: str, status: str):
    conn = get_db()
    conn.execute("""
        UPDATE commitments SET status=?, updated_at=? WHERE id=?
    """, (status, datetime.utcnow().isoformat(), commitment_id))
    conn.commit()
    conn.close()

def _claim_status(commitment_id: str, expected_current: str, new_status: str) -> bool:
    """
    Atomically transition status only if it still matches what the caller
    observed. The background scheduler tick and an explicit /simulate call
    can both invoke run_watch_loop() around the same moment; without this
    guard both would see the same item as still 'open' and double-send the
    same nudge/escalation. Returns True only if this call won the race.
    """
    conn = get_db()
    cur = conn.execute("""
        UPDATE commitments SET status=?, updated_at=? WHERE id=? AND status=?
    """, (new_status, datetime.utcnow().isoformat(), commitment_id, expected_current))
    conn.commit()
    won = cur.rowcount > 0
    conn.close()
    return won

def _log_event(commitment_id: str, event: str, detail: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO commitment_history (commitment_id, event, detail, at)
        VALUES (?, ?, ?, ?)
    """, (commitment_id, event, detail, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def _update_person_stats(person: str, event: str):
    conn = get_db()
    field = {"on_time": "on_time", "missed": "missed", "renegotiated": "renegotiated"}.get(event)
    if field:
        conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
        conn.commit()
    conn.close()

def _is_quiet_hours(now: datetime) -> bool:
    return now.hour >= QUIET_HOURS_START or now.hour < QUIET_HOURS_END
