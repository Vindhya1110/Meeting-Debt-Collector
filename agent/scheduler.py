"""
THE AUTONOMOUS CORE — pure deterministic rules, no LLM calls.
LLM is invoked ONLY inside nudger.py for message text generation.
"""
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import get_db, get_agent_now, log_event

NUDGE_H = float(os.getenv("NUDGE_HOURS_BEFORE", "24"))
ESCALATE_H = float(os.getenv("ESCALATE_HOURS_BEFORE", "6"))
QH_START = int(os.getenv("QUIET_HOURS_START", "22"))
QH_END = int(os.getenv("QUIET_HOURS_END", "8"))
EXAM_MODE = os.getenv("EXAM_MODE", "false").lower() == "true"
INTERVAL = int(os.getenv("WATCH_INTERVAL_SECONDS", "10"))

_scheduler = BackgroundScheduler()

def start():
    _scheduler.add_job(tick, "interval", seconds=INTERVAL,
                        id="watch", replace_existing=True)
    _scheduler.start()
    print(f"[Scheduler] Watch loop started - ticking every {INTERVAL}s")

def stop():
    _scheduler.shutdown(wait=False)

def tick():
    now = get_agent_now()
    if _quiet(now):
        return

    conn = get_db()
    rows = conn.execute("""
        SELECT c.*, m.title as meeting_title, m.owner as meeting_owner
        FROM commitments c
        JOIN meetings m ON c.meeting_id=m.id
        WHERE c.status IN ('open','nudged','escalated')
          AND c.deadline IS NOT NULL AND c.deadline != ''
    """).fetchall()
    conn.close()

    for r in rows:
        c = dict(r)
        try:
            dl = datetime.fromisoformat(c["deadline"])
            h_until = (dl - now).total_seconds() / 3600
        except (ValueError, TypeError):
            continue

        if h_until <= NUDGE_H and c["status"] == "open":
            if not _claim(c["id"], "open", "nudged"):
                continue  # another tick already handled this item
            # Log immediately on claiming, before the slower nudge-generation
            # LLM call + delivery — otherwise a fast escalation from a
            # concurrent tick can log before a slower nudge that actually
            # happened first, making the history read out of order.
            log_event(c["id"], "nudged", f"T-{h_until:.1f}h")
            _inc_nudge(c["id"])
            from nudger import send_nudge
            send_nudge(c, h_until)

        elif h_until <= ESCALATE_H and c["status"] == "nudged":
            if not _claim(c["id"], "nudged", "escalated"):
                continue
            log_event(c["id"], "escalated")
            from nudger import send_escalation
            send_escalation(c)

        elif h_until < 0 and c["status"] in ("open", "nudged", "escalated"):
            if not _claim(c["id"], c["status"], "missed"):
                continue
            log_event(c["id"], "missed", "deadline passed")
            _bump(c["owner"], "missed")
            cascade(c["id"], abs(h_until), c.get("normalized_task", "?"))
            _check_reassignment(c)

def cascade(commitment_id: str, delay_h: float, upstream_task: str):
    """Propagate deadline slip to all downstream dependents recursively."""
    conn = get_db()
    deps = conn.execute("""
        SELECT * FROM commitments
        WHERE depends_on=? AND status IN ('open','nudged')
    """, (commitment_id,)).fetchall()
    conn.close()

    for dep in deps:
        d = dict(dep)
        try:
            new_dl = (datetime.fromisoformat(d["deadline"])
                      + timedelta(hours=delay_h)).isoformat()
        except (ValueError, TypeError):
            continue
        conn = get_db()
        conn.execute("UPDATE commitments SET deadline=?,updated_at=? WHERE id=?",
                     (new_dl, datetime.utcnow().isoformat(), d["id"]))
        conn.commit()
        conn.close()
        from nudger import send_cascade
        send_cascade(d, delay_h, upstream_task)
        log_event(d["id"], "cascade_shifted", f"+{delay_h:.0f}h from {upstream_task}")
        cascade(d["id"], delay_h, d.get("normalized_task", "?"))

def _check_reassignment(c: dict):
    conn = get_db()
    stat = conn.execute("SELECT * FROM person_stats WHERE person=?",
                         (c["owner"],)).fetchone()
    open_n = conn.execute("""SELECT COUNT(*) as n FROM commitments
        WHERE owner=? AND status IN ('open','nudged','escalated')""",
        (c["owner"],)).fetchone()["n"]
    conn.close()
    if stat and stat["avg_completion_per_week"] and open_n > stat["avg_completion_per_week"] * 1.5:
        from nudger import send_reassignment
        send_reassignment(c, open_n, stat["avg_completion_per_week"])

def _claim(cid: str, expected_current: str, new_status: str) -> bool:
    """
    Atomically transition status only if it still matches what the caller
    observed. The background tick and an explicit /simulate call can both
    invoke tick() around the same moment; without this guard both would see
    the same item as still eligible and double-send the same nudge/escalation.
    Returns True only if this call won the race.
    """
    conn = get_db()
    cur = conn.execute(
        "UPDATE commitments SET status=?,updated_at=? WHERE id=? AND status=?",
        (new_status, datetime.utcnow().isoformat(), cid, expected_current)
    )
    conn.commit()
    won = cur.rowcount > 0
    conn.close()
    return won

def _inc_nudge(cid):
    conn = get_db()
    conn.execute("UPDATE commitments SET nudge_count=nudge_count+1 WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def _bump(person, field):
    conn = get_db()
    conn.execute(f"UPDATE person_stats SET {field}={field}+1 WHERE person=?", (person,))
    conn.commit()
    conn.close()

def _quiet(now: datetime) -> bool:
    if EXAM_MODE:
        return False
    return now.hour >= QH_START or now.hour < QH_END
