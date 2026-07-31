import sqlite3
from datetime import datetime

DB_PATH = "meeting_debt.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        date TEXT NOT NULL,
        owner TEXT NOT NULL,
        attendees TEXT NOT NULL,       -- JSON array of {name, email, slack_handle}
        transcript TEXT DEFAULT '',
        audio_path TEXT DEFAULT '',
        status TEXT DEFAULT 'active',  -- active | finalized | closed
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS commitments (
        id TEXT PRIMARY KEY,
        meeting_id TEXT NOT NULL,
        owner TEXT NOT NULL,
        beneficiary TEXT DEFAULT '',
        commitment_text TEXT NOT NULL,     -- verbatim quote from transcript
        normalized_task TEXT NOT NULL,     -- cleaned-up action description
        embedding TEXT DEFAULT '',         -- JSON float array for similarity
        explicit_deadline TEXT DEFAULT '', -- e.g. "Thursday"
        deadline TEXT DEFAULT '',          -- resolved ISO timestamp
        original_deadline TEXT DEFAULT '', -- set once, never overwritten
        deadline_clue TEXT DEFAULT '',     -- e.g. "before the client call"
        status TEXT DEFAULT 'open',
        -- open | nudged | escalated | done | renegotiated | reassigned | missed
        -- | needs_clarification | review
        owner_type TEXT DEFAULT 'person',  -- person | ownerless | vague_intention
        item_type TEXT DEFAULT 'self_commitment',
        -- self_commitment | assignment | meeting_request
        assigned_by TEXT DEFAULT '',
        confidence REAL DEFAULT 0.9,
        depends_on TEXT DEFAULT '',        -- commitment ID this blocks on
        nudge_count INTEGER DEFAULT 0,
        timestamp_sec INTEGER DEFAULT 0,   -- position in transcript audio
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (meeting_id) REFERENCES meetings(id)
    );

    CREATE TABLE IF NOT EXISTS commitment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_id TEXT NOT NULL,
        event TEXT NOT NULL,               -- extracted|nudged|escalated|done|missed|renegotiated|reassigned
        detail TEXT DEFAULT '',
        at TEXT NOT NULL,
        FOREIGN KEY (commitment_id) REFERENCES commitments(id)
    );

    CREATE TABLE IF NOT EXISTS agenda_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id TEXT NOT NULL,
        slot_id TEXT NOT NULL,
        label TEXT NOT NULL,
        required INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',     -- pending | covered | missed
        evidence_quote TEXT DEFAULT '',
        covered_at TEXT DEFAULT '',
        UNIQUE(meeting_id, slot_id)
    );

    CREATE TABLE IF NOT EXISTS person_stats (
        person TEXT PRIMARY KEY,
        email TEXT DEFAULT '',
        slack_handle TEXT DEFAULT '',
        committed INTEGER DEFAULT 0,
        on_time INTEGER DEFAULT 0,
        renegotiated INTEGER DEFAULT 0,
        missed INTEGER DEFAULT 0,
        avg_completion_per_week REAL DEFAULT 2.0
    );

    CREATE TABLE IF NOT EXISTS agent_clock (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        simulated_now TEXT NOT NULL
    );
    """)

    # Seed agent clock with real current time
    now = datetime.utcnow().isoformat()
    c.execute("""
        INSERT OR IGNORE INTO agent_clock (id, simulated_now) VALUES (1, ?)
    """, (now,))

    # Seed person_stats with realistic demo history
    demo_people = [
        ("Alice", "alice@team.com", "@alice", 8, 6, 1, 1, 3.0),
        ("Bob", "bob@team.com", "@bob", 6, 3, 1, 2, 1.5),
        ("Rohith", "rohith@team.com", "@rohith", 10, 4, 2, 4, 2.0),
        ("Priya", "priya@team.com", "@priya", 7, 7, 0, 0, 3.5),
    ]
    c.executemany("""
        INSERT OR IGNORE INTO person_stats
        (person, email, slack_handle, committed, on_time, renegotiated, missed, avg_completion_per_week)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, demo_people)

    conn.commit()
    conn.close()

def get_agent_now():
    conn = get_db()
    row = conn.execute("SELECT simulated_now FROM agent_clock WHERE id=1").fetchone()
    conn.close()
    return datetime.fromisoformat(row["simulated_now"])

def advance_agent_clock(hours: float):
    from datetime import timedelta
    now = get_agent_now()
    new_now = (now + timedelta(hours=hours)).isoformat()
    conn = get_db()
    conn.execute("UPDATE agent_clock SET simulated_now=? WHERE id=1", (new_now,))
    conn.commit()
    conn.close()
    return new_now
