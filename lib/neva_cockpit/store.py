"""sqlite3 store for the cockpit. Standard library only.

Three tables: `sessions` (one row per harness session the ingester has seen),
`ingest_offsets` (how far the ingester has read each source file, so re-running it is cheap and
idempotent) and `ingest_notes` (hook errors and rejected source lines, kept after their offset
has moved on so every view can still show them). `schema_version` holds the single row that records which numbered migration in
MIGRATIONS this database has applied.
"""
import datetime
import json
import os
import sqlite3

from . import hooks_common

MIGRATIONS = [
    (1, """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            harness TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            branch TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            last_activity TEXT NOT NULL DEFAULT '',
            cost_usd REAL NOT NULL DEFAULT 0,
            context_pct REAL NOT NULL DEFAULT 0,
            risk_flags TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE ingest_offsets (
            path TEXT PRIMARY KEY,
            offset INTEGER NOT NULL DEFAULT 0,
            mtime REAL NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0
        );
    """),
    (2, """
        CREATE TABLE ingest_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            seen_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX ingest_notes_kind ON ingest_notes (kind, id);
    """),
    (3, """
        ALTER TABLE ingest_offsets ADD COLUMN inode INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE ingest_offsets ADD COLUMN signature TEXT NOT NULL DEFAULT '';
    """),
    (4, """
        ALTER TABLE sessions ADD COLUMN last_activity_at REAL;
    """),
]

_SESSION_COLUMNS = ("id", "harness", "project", "branch", "started_at", "last_activity",
                    "cost_usd", "context_pct", "risk_flags", "last_activity_at")


def normalize_timestamp(value):
    """'2026-10-05 10:30' (session summaries) and '2026-10-05T10:30:00' (costs, codex) sort
    together once the date/time separator is the same, so every source's value is stored with
    'T'. Anything that does not look like a date is returned unchanged."""
    value = (value or "").strip()
    if len(value) > 10 and value[4] == "-" and value[7] == "-" and value[10] == " ":
        value = value[:10] + "T" + value[11:]
    return value


def parse_instant(value):
    """Seconds since the epoch for an ISO-8601 timestamp, or None when it is not one. An offset
    or a trailing Z is honoured. A naive time (session summaries write '2026-10-05 10:30') is
    read in the timezone the hooks write in: NEVA_TIMEZONE or TIMEZONE from the identity file,
    else the machine's local zone, which is what hooks_common.now() uses."""
    text = normalize_timestamp(value)
    if not text:
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        zone = hooks_common.now().tzinfo
        if zone is not None:
            moment = moment.replace(tzinfo=zone)
    try:
        return moment.timestamp()  # a naive moment left here is read as machine-local time
    except (OverflowError, OSError, ValueError):
        return None


def default_db_path():
    return os.path.join(hooks_common.sub_dir("cockpit"), "cockpit.db")


class Store:
    NOTES_KEPT = 200  # per kind; older notes are pruned on every add

    def __init__(self, path=None):
        self.path = path or default_db_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        try:
            self._migrate()
            self._backfill_activity_instants()
        except BaseException:
            self.conn.close()
            raise

    def _migrate(self):
        """Apply each pending migration and its version stamp in one transaction. sqlite DDL is
        transactional, so an error or a crash mid-migration rolls the whole step back and the
        next open retries it, instead of finding tables that exist with no version recorded."""
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        self.conn.commit()
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            try:
                self.conn.executescript(
                    "BEGIN;\n" + sql.strip().rstrip(";") + ";\n"
                    "DELETE FROM schema_version;\n"
                    f"INSERT INTO schema_version (version) VALUES ({int(version)});\n"
                    "COMMIT;")
            except sqlite3.Error:
                if self.conn.in_transaction:
                    self.conn.rollback()
                raise
            current = version

    def _backfill_activity_instants(self):
        """Rows written before migration 4 carry last_activity but no instant to sort by."""
        rows = self.conn.execute(
            "SELECT id, last_activity FROM sessions "
            "WHERE last_activity_at IS NULL AND last_activity != ''").fetchall()
        for row in rows:
            at = parse_instant(row["last_activity"])
            if at is not None:
                self.conn.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                                  (at, row["id"]))
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------------------------------------------------------------- sessions

    def upsert_session(self, session):
        """session: dict with at least 'id'. Only the keys present are changed; a column this
        call does not mention keeps whatever an earlier ingest source already wrote for that
        session id (different sources own different columns: the session summary owns project
        and branch, costs.jsonl owns cost_usd, observations own risk_flags). last_activity is
        the exception: it only ever moves forward, whichever source reports it. Missing fields
        default sanely only for a brand new row. A row with the same id is updated in place,
        never duplicated."""
        sid = session["id"]
        existing = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        base = dict(existing) if existing else {c: None for c in _SESSION_COLUMNS}
        try:
            base["risk_flags"] = json.loads(base["risk_flags"]) if base.get("risk_flags") else []
        except (TypeError, ValueError):
            base["risk_flags"] = []
        for key in _SESSION_COLUMNS:
            if key in ("id", "last_activity", "last_activity_at") or key not in session:
                continue
            base[key] = session[key]
        if "last_activity" in session:
            # Sources disagree on when a session was last active (a summary written at 10:30
            # local, a cost row stamped in UTC, a codex mtime with its own offset). Compare the
            # instants, not the strings: activity only moves forward in real time, the same
            # instant in another offset is not a move, and empty never wins. A value that does
            # not parse loses to one that does, and is compared as text only against another
            # unparseable one.
            incoming = normalize_timestamp(session["last_activity"])
            current = normalize_timestamp(base.get("last_activity"))
            new_at = parse_instant(incoming)
            cur_at = parse_instant(current) if current else None
            if incoming and (not current
                             or (new_at is not None and (cur_at is None or new_at > cur_at))
                             or (new_at is None and cur_at is None and incoming > current)):
                base["last_activity"] = incoming
        base["last_activity_at"] = parse_instant(base.get("last_activity"))
        values = {
            "id": sid,
            "harness": base.get("harness") or "",
            "project": base.get("project") or "",
            "branch": base.get("branch") or "",
            "started_at": base.get("started_at") or "",
            "last_activity": base.get("last_activity") or "",
            "cost_usd": float(base.get("cost_usd") or 0),
            "context_pct": float(base.get("context_pct") or 0),
            "risk_flags": json.dumps(list(base.get("risk_flags") or [])),
            "last_activity_at": base.get("last_activity_at"),
        }
        columns = ", ".join(_SESSION_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _SESSION_COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _SESSION_COLUMNS if c != "id")
        self.conn.execute(
            f"INSERT INTO sessions ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            values,
        )
        self.conn.commit()

    def add_risk_flags(self, session_id, flags):
        """Union new flags into the session's existing risk_flags, deduped, order preserved.
        Unlike upsert_session's risk_flags key (an explicit set), this accumulates across many
        separate observation records for the same session."""
        if not flags:
            return
        existing = self.conn.execute(
            "SELECT risk_flags FROM sessions WHERE id = ?", (session_id,)).fetchone()
        try:
            current = json.loads(existing["risk_flags"]) if existing else []
        except (TypeError, ValueError):
            current = []
        merged = list(current)
        for flag in flags:
            if flag not in merged:
                merged.append(flag)
        self.upsert_session({"id": session_id, "risk_flags": merged})

    def sessions(self):
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY last_activity_at IS NULL, last_activity_at DESC, "
            "last_activity DESC").fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["risk_flags"] = json.loads(d["risk_flags"])
            except (TypeError, ValueError):
                d["risk_flags"] = []
            out.append(d)
        return out

    # ---------------------------------------------------------------- ingest offsets

    def get_offset(self, path):
        row = self.conn.execute(
            "SELECT offset, mtime, size, inode, signature FROM ingest_offsets WHERE path = ?",
            (path,)).fetchone()
        return dict(row) if row else None

    def set_offset(self, path, offset, mtime, size, inode=0, signature=""):
        self.advance(path, offset, mtime, size, inode, signature)

    def advance(self, path, offset, mtime, size, inode=0, signature="", notes=()):
        """Store the notes a read produced and move the file's offset past it, in ONE
        transaction. Notes first, offset second, both or neither: an offset that advanced
        without its notes would make the next read skip them for good. inode and signature
        identify the file the offset belongs to (see ingest._changed). notes: iterable of
        (kind, details, seen_at)."""
        try:
            for kind, details, seen_at in notes:
                self._insert_notes(kind, details, seen_at)
            self.conn.execute(
                "INSERT INTO ingest_offsets (path, offset, mtime, size, inode, signature) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET offset = excluded.offset, "
                "mtime = excluded.mtime, size = excluded.size, inode = excluded.inode, "
                "signature = excluded.signature",
                (path, offset, mtime, size, int(inode), signature),
            )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    # ---------------------------------------------------------------- ingest notes

    def _insert_notes(self, kind, details, seen_at):
        details = [str(d) for d in details if str(d).strip()]
        if not details:
            return
        self.conn.executemany(
            "INSERT INTO ingest_notes (kind, detail, seen_at) VALUES (?, ?, ?)",
            [(kind, d, seen_at) for d in details])
        self.conn.execute(
            "DELETE FROM ingest_notes WHERE kind = ? AND id NOT IN "
            "(SELECT id FROM ingest_notes WHERE kind = ? ORDER BY id DESC LIMIT ?)",
            (kind, kind, self.NOTES_KEPT))

    def add_notes(self, kind, details, seen_at=""):
        try:
            self._insert_notes(kind, details, seen_at)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def recent_notes(self, kind, limit=20):
        rows = self.conn.execute(
            "SELECT detail, seen_at FROM ingest_notes WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, int(limit))).fetchall()
        return [dict(row) for row in rows]
