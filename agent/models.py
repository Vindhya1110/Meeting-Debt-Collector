import sqlite3
from datetime import datetime

DB_PATH = "meeting_debt.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meetings (
        id              TEXT PRIMARY KEY,
        title           TEXT NOT NULL,
        type            TEXT DEFAULT 'club_meeting',
        platform        TEXT DEFAULT 'unknown',
        date            TEXT NOT NULL,
        owner           TEXT DEFAULT '',
        attendees       TEXT DEFAULT '[]',
        transcript      TEXT DEFAULT '',
        pre_brief       TEXT DEFAULT '',
        mom             TEXT DEFAULT '',
        status          TEXT DEFAULT 'active',
        notion_page_id  TEXT DEFAULT '',
        created_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitments (
        id                  TEXT PRIMARY KEY,
        meeting_id          TEXT NOT NULL,
        owner               TEXT NOT NULL,
        beneficiary         TEXT DEFAULT '',
        commitment_text     TEXT NOT NULL,
        normalized_task     TEXT NOT NULL,
        explicit_deadline   TEXT DEFAULT '',
        deadline            TEXT DEFAULT '',
        original_deadline   TEXT DEFAULT '',
        deadline_clue       TEXT DEFAULT '',
        status              TEXT DEFAULT 'open',
        owner_type          TEXT DEFAULT 'person',
        item_type           TEXT DEFAULT 'self_commitment',
        assigned_by         TEXT DEFAULT '',
        confidence          REAL DEFAULT 0.9,
        depends_on          TEXT DEFAULT '',
        nudge_count         INTEGER DEFAULT 0,
        timestamp_sec       INTEGER DEFAULT 0,
        warning             TEXT DEFAULT '',
        notion_page_id      TEXT DEFAULT '',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitment_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_id   TEXT NOT NULL,
        event           TEXT NOT NULL,
        detail          TEXT DEFAULT '',
        at              TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS agenda_state (
        meeting_id      TEXT NOT NULL,
        slot_id         TEXT NOT NULL,
        label           TEXT NOT NULL,
        required        INTEGER DEFAULT 1,
        status          TEXT DEFAULT 'pending',
        evidence_quote  TEXT DEFAULT '',
        covered_at      TEXT DEFAULT '',
        PRIMARY KEY (meeting_id, slot_id)
    );

    CREATE TABLE IF NOT EXISTS person_stats (
        person                  TEXT PRIMARY KEY,
        committed               INTEGER DEFAULT 0,
        on_time                 INTEGER DEFAULT 0,
        renegotiated            INTEGER DEFAULT 0,
        missed                  INTEGER DEFAULT 0,
        avg_completion_per_week REAL DEFAULT 2.0,
        notion_page_id          TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS calendar_drafts (
        id              TEXT PRIMARY KEY,
        commitment_id   TEXT NOT NULL,
        summary         TEXT NOT NULL,
        start_iso       TEXT NOT NULL,
        duration_min    INTEGER DEFAULT 15,
        attendees       TEXT DEFAULT '[]',
        status          TEXT DEFAULT 'pending',
        created_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS agent_clock (
        id              INTEGER PRIMARY KEY CHECK (id=1),
        simulated_now   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notion_ids (
        key             TEXT PRIMARY KEY,
        notion_id       TEXT NOT NULL
    );
    """)

    conn.execute(
        "INSERT OR IGNORE INTO agent_clock (id, simulated_now) VALUES (1, ?)",
        (datetime.utcnow().isoformat(),)
    )

    # Seed demo people with realistic history
    for row in [
        ("Alice",  8, 6, 1, 1, 3.0),
        ("Bob",    6, 3, 1, 2, 1.5),
        ("Rohith", 10, 4, 2, 4, 2.0),
        ("Priya",  7, 7, 0, 0, 3.5),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO person_stats "
            "(person,committed,on_time,renegotiated,missed,avg_completion_per_week) "
            "VALUES (?,?,?,?,?,?)", row
        )
    conn.commit()
    conn.close()

def get_agent_now():
    conn = get_db()
    row = conn.execute("SELECT simulated_now FROM agent_clock WHERE id=1").fetchone()
    conn.close()
    return datetime.fromisoformat(row["simulated_now"])

def advance_clock(hours: float) -> str:
    from datetime import timedelta
    new = (get_agent_now() + timedelta(hours=hours)).isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=? WHERE id=1", (new,))
    conn.commit()
    conn.close()
    return new

def log_event(commitment_id: str, event: str, detail: str = ""):
    conn = get_db()
    conn.execute(
        "INSERT INTO commitment_history (commitment_id,event,detail,at) VALUES (?,?,?,?)",
        (commitment_id, event, detail, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def set_notion_id(key: str, notion_id: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO notion_ids (key,notion_id) VALUES (?,?)",
                 (key, notion_id))
    conn.commit()
    conn.close()

def get_notion_id(key: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT notion_id FROM notion_ids WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["notion_id"] if row else ""
