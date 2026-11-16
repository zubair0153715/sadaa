# -*- coding: utf-8 -*-
"""Sadaa — SQLite storage.

Plain sqlite3, no ORM. One connection per call; rows returned as dicts.
DB path comes from SADAA_DB env or defaults to data/sadaa.db (created on
startup). Tests point it at a temp file.
"""
import json
import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.environ.get("SADAA_DB", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sadaa.db"))


def set_db_path(path):
    global DB_PATH
    DB_PATH = path


def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    persona TEXT NOT NULL, greeting TEXT NOT NULL,
    voice_lang TEXT NOT NULL DEFAULT 'en-US', voice_name TEXT DEFAULT '',
    voice_rate REAL NOT NULL DEFAULT 1.0, voice_pitch REAL NOT NULL DEFAULT 1.0,
    system_prompt TEXT NOT NULL, tools TEXT NOT NULL DEFAULT '[]',
    intents TEXT NOT NULL DEFAULT '[]', sample_dialogue TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, direction TEXT NOT NULL,
    contact_name TEXT DEFAULT '', contact_ref TEXT DEFAULT '',
    state TEXT NOT NULL DEFAULT 'QUEUED', outcome TEXT DEFAULT '',
    csat INTEGER, started_at TEXT NOT NULL, ended_at TEXT DEFAULT '',
    duration_sec INTEGER NOT NULL DEFAULT 0,
    supervisor_active INTEGER NOT NULL DEFAULT 0,
    handoff INTEGER NOT NULL DEFAULT 0,
    context TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL,
    speaker TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(id)
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    phone TEXT DEFAULT '', email TEXT DEFAULT '', interest TEXT DEFAULT '',
    source TEXT DEFAULT 'call', status TEXT NOT NULL DEFAULT 'new',
    notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
    description TEXT DEFAULT '', priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'open', caller_name TEXT DEFAULT '',
    call_id TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
    time TEXT NOT NULL, name TEXT NOT NULL, service TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'booked', call_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
    date TEXT NOT NULL, time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'free',
    appointment_id INTEGER, PRIMARY KEY (date, time)
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    agent_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
CREATE TABLE IF NOT EXISTS campaign_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL,
    ref TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    call_id TEXT DEFAULT '',
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);
CREATE TABLE IF NOT EXISTS faqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL,
    answer TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS accounts (
    ref TEXT PRIMARY KEY, name TEXT NOT NULL, balance REAL NOT NULL DEFAULT 0,
    due_date TEXT DEFAULT '', demo INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS supervisor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL,
    action TEXT NOT NULL, message TEXT DEFAULT '', created_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(id)
);
"""


def init_db(seed=True):
    from . import agents as agents_mod
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        if seed:
            _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn):
    from . import agents as agents_mod
    now = _now()
    if conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
        for a in agents_mod.AGENTS:
            conn.execute(
                """INSERT INTO agents (id, name, role, persona, greeting,
                    voice_lang, voice_name, voice_rate, voice_pitch,
                    system_prompt, tools, intents, sample_dialogue, active, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (a["id"], a["name"], a["role"], a["persona"], a["greeting"],
                 a["voice"]["lang"], a["voice"].get("name", ""),
                 a["voice"].get("rate", 1.0), a["voice"].get("pitch", 1.0),
                 a["system_prompt"], json.dumps(a["tools"]),
                 json.dumps(a["intents"]), json.dumps(a["sample_dialogue"]),
                 1, now))
    if conn.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] == 0:
        for q, a, kw in agents_mod.FAQS:
            conn.execute("INSERT INTO faqs (question, answer, keywords) VALUES (?,?,?)",
                         (q, a, kw))
    if conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0] == 0:
        for i in range(1, 8):
            d = (date.today() + timedelta(days=i)).isoformat()
            for h in range(9, 18):
                conn.execute("INSERT OR IGNORE INTO slots (date, time) VALUES (?,?)",
                             (d, "%02d:00" % h))
    if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        for ref, name, bal, due in agents_mod.DEMO_ACCOUNTS:
            conn.execute("INSERT OR IGNORE INTO accounts (ref, name, balance, due_date, demo) "
                         "VALUES (?,?,?,?,1)", (ref, name, bal, due))


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
