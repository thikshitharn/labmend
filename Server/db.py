"""Database layer (SQLite: built into Python, stored in one file, labmend.db)."""
import json
import sqlite3
import threading
import time

import config

_lock = threading.Lock()   # only one thread writes at a time

# States where a problem is still "open" (not finished).
OPEN_STATES = ("diagnosing", "pending", "approved", "applied", "blocked", "manual", "acknowledged")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id   TEXT PRIMARY KEY,
    hostname  TEXT,
    python    TEXT,
    status    TEXT,
    summary   TEXT,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT,
    signature   TEXT,
    kind        TEXT,
    severity    TEXT,
    error_text  TEXT,
    explanation TEXT,
    fix_json    TEXT,
    source      TEXT,
    state       TEXT,
    result      TEXT,
    created     REAL,
    updated     REAL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row      # rows behave like dicts: row["node_id"]
    return conn


def init_db():
    with _lock, connect() as conn:
        conn.executescript(SCHEMA)
        try:   # add the column to databases created before auto-heal existed
            conn.execute("ALTER TABLE issues ADD COLUMN approved_by TEXT")
        except sqlite3.OperationalError:
            pass   # column already exists


# ---------------- settings (active course, auto-heal on/off) ----------------
def get_setting(key, default=None):
    with _lock, connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with _lock, connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def to_issue(row):
    d = dict(row)
    d["fix"] = json.loads(d.pop("fix_json")) if d["fix_json"] else None
    return d


# ---------------- nodes ----------------
def save_node(node_id, hostname, python, status, summary):
    with _lock, connect() as conn:
        conn.execute(
            """INSERT INTO nodes (node_id, hostname, python, status, summary, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET hostname=excluded.hostname,
                 python=excluded.python, status=excluded.status,
                 summary=excluded.summary, last_seen=excluded.last_seen""",
            (node_id, hostname, python, status, summary, time.time()))


def all_nodes():
    with _lock, connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM nodes ORDER BY node_id")]


# ---------------- issues ----------------
def add_issue(node_id, signature, kind, severity, error_text, explanation, fix, source, state):
    now = time.time()
    with _lock, connect() as conn:
        cur = conn.execute(
            """INSERT INTO issues (node_id, signature, kind, severity, error_text, explanation,
                                   fix_json, source, state, created, updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_id, signature, kind, severity, error_text, explanation,
             json.dumps(fix) if fix else None, source, state, now, now))
        return cur.lastrowid


def update_issue(issue_id, **fields):
    if "fix" in fields:
        fix = fields.pop("fix")
        fields["fix_json"] = json.dumps(fix) if fix else None
    fields["updated"] = time.time()
    columns = ", ".join(f"{name}=?" for name in fields)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE issues SET {columns} WHERE id=?", (*fields.values(), issue_id))


def get_issue(issue_id):
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        return to_issue(row) if row else None


def open_issues(node_id):
    marks = ",".join("?" * len(OPEN_STATES))
    with _lock, connect() as conn:
        rows = conn.execute(f"SELECT * FROM issues WHERE node_id=? AND state IN ({marks})",
                            (node_id, *OPEN_STATES))
        return [to_issue(r) for r in rows]


def find_open_issue(node_id, signature):
    for issue in open_issues(node_id):
        if issue["signature"] == signature:
            return issue
    return None


def issues_with(state, node_id=None, signature=None):
    sql, args = "SELECT * FROM issues WHERE state=?", [state]
    if node_id:
        sql, args = sql + " AND node_id=?", args + [node_id]
    if signature:
        sql, args = sql + " AND signature=?", args + [signature]
    with _lock, connect() as conn:
        return [to_issue(r) for r in conn.execute(sql + " ORDER BY id", args)]


def recent_issues(limit=150):
    with _lock, connect() as conn:
        rows = conn.execute("SELECT * FROM issues ORDER BY id DESC LIMIT ?", (limit,))
        return [to_issue(r) for r in rows]
