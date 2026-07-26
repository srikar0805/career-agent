#!/usr/bin/env python3
"""SQLite schema for the career pipeline.

The reference project this replaces used flat CSVs. CSVs cannot answer the
questions that actually matter during a job search: which stage am I losing
people at, what has gone quiet, who do I already know at this company. Those
are joins, so this is a database.

Usage:
    python scripts/db.py init      # create or migrate
    python scripts/db.py schema    # print current schema
    python scripts/db.py reset     # drop everything (asks first)
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "pipeline.db"

# The application lifecycle. Order matters: `pipeline.py stats` computes
# stage-to-stage conversion by walking this list.
STAGES = [
    "discovered",    # found by discover.py, not yet triaged
    "shortlisted",   # worth applying to
    "applied",       # submitted
    "screening",     # recruiter screen scheduled or done
    "interviewing",  # technical or onsite loop
    "offer",
]

TERMINAL = ["accepted", "rejected", "withdrawn", "ghosted"]
ALL_STATUSES = STAGES + TERMINAL

# Reusable across job applications, grad programs, and freelance clients.
# The domain differs, the pipeline mechanics do not.
TRACKS = ["job", "grad", "freelance"]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY,
    track         TEXT NOT NULL DEFAULT 'job',
    company       TEXT NOT NULL,
    role          TEXT NOT NULL,
    url           TEXT,
    source        TEXT,               -- greenhouse | lever | ashby | remoteok | referral | manual
    location      TEXT,
    remote        TEXT,               -- onsite | hybrid | remote
    status        TEXT NOT NULL DEFAULT 'discovered',
    fit_score     INTEGER,            -- 0-100 from the judge, null until scored
    sponsors      INTEGER,            -- 1 yes, 0 no, null unknown
    comp_min      INTEGER,
    comp_max      INTEGER,
    jd_text       TEXT,               -- full posting, so we can re-analyze offline
    notes         TEXT,
    discovered_at TEXT NOT NULL,
    applied_at    TEXT,
    closed_at     TEXT,
    updated_at    TEXT NOT NULL,
    UNIQUE(company, role, url)
);

CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    title        TEXT,
    company      TEXT,
    email        TEXT,
    linkedin_url TEXT,
    -- 'connection' means they are in your LinkedIn export, which is the
    -- difference between a warm intro and a cold message.
    relationship TEXT DEFAULT 'cold',  -- cold | connection | colleague | referrer
    connected_on TEXT,
    notes        TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(name, company)
);

CREATE TABLE IF NOT EXISTS interactions (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    contact_id     INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    kind           TEXT NOT NULL,   -- cold_message | application | follow_up | screen | interview | offer_call | rejection
    direction      TEXT NOT NULL,   -- out | in
    channel        TEXT,            -- linkedin | email | phone | portal
    summary        TEXT NOT NULL,
    body           TEXT,            -- what was actually sent, so follow-ups never repeat it
    occurred_at    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    contact_id     INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    kind           TEXT NOT NULL,   -- apply | follow_up | research | prep | outreach
    description    TEXT NOT NULL,
    due_date       TEXT,
    status         TEXT NOT NULL DEFAULT 'open',  -- open | done | dropped
    created_at     TEXT NOT NULL,
    completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,   -- resume | cover_letter | cold_message | interview_prep | follow_up | sop | pitch
    path           TEXT NOT NULL,
    score          INTEGER,
    verdict        TEXT,            -- REJECT | MAYBE | INTERVIEW from recruiter-screener
    evidence_ids   TEXT,            -- comma separated EV-* used, for traceability
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_status   ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_company  ON applications(company);
CREATE INDEX IF NOT EXISTS idx_app_track    ON applications(track);
CREATE INDEX IF NOT EXISTS idx_int_app      ON interactions(application_id);
CREATE INDEX IF NOT EXISTS idx_int_when     ON interactions(occurred_at);
CREATE INDEX IF NOT EXISTS idx_task_due     ON tasks(due_date, status);
CREATE INDEX IF NOT EXISTS idx_contact_co   ON contacts(company);
CREATE INDEX IF NOT EXISTS idx_art_app      ON artifacts(application_id);
"""


def now() -> str:
    """UTC ISO timestamp. Stored as text because SQLite has no date type."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"

    if cmd == "init":
        init()
        print(f"database ready at {DB_PATH}")
        return 0

    if cmd == "schema":
        conn = connect()
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
        ).fetchall()
        for r in rows:
            print(r["sql"], ";\n", sep="")
        return 0

    if cmd == "reset":
        if not DB_PATH.exists():
            print("nothing to reset")
            return 0
        answer = input(f"Delete {DB_PATH} and all pipeline history? type 'yes': ")
        if answer.strip() == "yes":
            DB_PATH.unlink()
            init()
            print("reset done")
        else:
            print("cancelled")
        return 0

    print(f"unknown command: {cmd}. Use init, schema, or reset.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
