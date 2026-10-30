"""SQLite store. One file in a private folder, outside any synced notes folder.

source_runs proves a read happened, so unknown is provable. facts holds pointers, one row per thing, with the time it
was first and last seen. candidates keeps one row per rule and subject for ever. Nothing here holds the text of a line:
line_sha256 proves what the line said without keeping it."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3

RETENTION_DAYS = 90
SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, looked_at TEXT NOT NULL, status TEXT NOT NULL,
    records INTEGER NOT NULL, denied INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, error TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts (
    source TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL, ts TEXT, value TEXT NOT NULL, path TEXT NOT NULL,
    line INTEGER, line_sha256 TEXT NOT NULL, first_seen TEXT NOT NULL, seen_at TEXT NOT NULL,
    PRIMARY KEY (source, kind, subject));
CREATE TABLE IF NOT EXISTS candidates (
    key TEXT PRIMARY KEY, rule TEXT NOT NULL, severity REAL NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
"""


class Store:
    def __init__(self, runtime):
        self.path = os.path.join(runtime, "engine.db")
        ensure_private_dir(runtime)
        fresh = not os.path.exists(self.path)
        if fresh:
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.executescript(SCHEMA)

    def last_look(self):
        row = self.db.execute("SELECT MAX(looked_at) FROM source_runs").fetchone()
        return row[0] if row else None

    def record(self, read, looked_at):
        self.db.execute(
            "INSERT INTO source_runs (source, looked_at, status, records, denied, path, sha256, error) VALUES (?,?,?,?,?,?,?,?)",
            (read.source, looked_at, read.status, len(read.facts), read.denied, read.path, read.sha256, read.error))
        for f in read.facts:
            self.db.execute(
                "INSERT INTO facts (source, kind, subject, ts, value, path, line, line_sha256, first_seen, seen_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (source, kind, subject) DO UPDATE SET "
                "ts=excluded.ts, value=excluded.value, path=excluded.path, line=excluded.line, "
                "line_sha256=excluded.line_sha256, seen_at=excluded.seen_at",
                (f.source, f.kind, f.subject, f.ts, json.dumps(f.value, sort_keys=True), f.path, f.line,
                 hashlib.sha256(f.quote.encode()).hexdigest(), looked_at, looked_at))

    def candidate(self, card, looked_at):
        self.db.execute(
            "INSERT INTO candidates (key, rule, severity, first_seen, last_seen) VALUES (?,?,?,?,?) "
            "ON CONFLICT (key) DO UPDATE SET severity=excluded.severity, last_seen=excluded.last_seen",
            (card.key, card.rule, card.severity, looked_at, looked_at))

    def prune(self, cutoff):
        self.db.execute("DELETE FROM source_runs WHERE looked_at < ?", (cutoff,))
        self.db.execute("DELETE FROM facts WHERE seen_at < ?", (cutoff,))

    def close(self):
        self.db.commit()
        self.db.close()


def ensure_private_dir(path):
    os.makedirs(path, exist_ok=True)
    os.chmod(path, 0o700)
