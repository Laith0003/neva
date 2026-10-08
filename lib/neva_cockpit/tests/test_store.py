import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import store  # noqa: E402


def make_session(**over):
    row = {
        "id": "sess-1",
        "harness": "claude",
        "project": "neva",
        "branch": "main",
        "started_at": "2026-10-05T10:00:00Z",
        "last_activity": "2026-10-05T10:05:00Z",
        "cost_usd": 0.42,
        "context_pct": 12.5,
        "risk_flags": ["destructive-bash"],
    }
    row.update(over)
    return row


class StoreSchemaTests(unittest.TestCase):
    def test_fresh_memory_db_has_both_tables(self):
        s = store.Store(":memory:")
        names = {r[0] for r in s.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("sessions", names)
        self.assertIn("ingest_offsets", names)
        self.assertIn("schema_version", names)
        s.close()

    def test_schema_version_records_latest_migration(self):
        s = store.Store(":memory:")
        row = s.conn.execute("SELECT version FROM schema_version").fetchone()
        self.assertEqual(row[0], store.MIGRATIONS[-1][0])
        s.close()

    def test_migrations_are_idempotent_on_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cockpit.db")
            s1 = store.Store(path)
            s1.close()
            s2 = store.Store(path)
            row = s2.conn.execute("SELECT version FROM schema_version").fetchone()
            self.assertEqual(row[0], store.MIGRATIONS[-1][0])
            count = s2.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            self.assertEqual(count, 1)
            s2.close()

    def test_an_interrupted_migration_leaves_nothing_half_applied(self):
        """Review L1: DDL and the version stamp commit together or not at all, so reopening
        after a failure mid-migration retries cleanly instead of dying on CREATE TABLE."""
        good = list(store.MIGRATIONS)
        broken = good + [(99, "CREATE TABLE half_done (x INTEGER); CREATE TABLE broken (")]
        fixed = good + [(99, "CREATE TABLE half_done (x INTEGER);")]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cockpit.db")
            with mock.patch.object(store, "MIGRATIONS", broken):
                with self.assertRaises(sqlite3.Error):
                    store.Store(path)
            probe = sqlite3.connect(path)
            names = {r[0] for r in probe.execute("SELECT name FROM sqlite_master")}
            version = probe.execute("SELECT version FROM schema_version").fetchone()[0]
            probe.close()
            self.assertNotIn("half_done", names)
            self.assertEqual(version, good[-1][0])
            with mock.patch.object(store, "MIGRATIONS", fixed):
                s = store.Store(path)
                self.assertEqual(s.conn.execute(
                    "SELECT version FROM schema_version").fetchone()[0], 99)
                s.close()

    def test_migrations_applied_in_order(self):
        self.assertEqual([v for v, _ in store.MIGRATIONS], sorted(v for v, _ in store.MIGRATIONS))


class SessionRowTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(":memory:")

    def tearDown(self):
        self.s.close()

    def test_upsert_then_list_round_trips_fields(self):
        self.s.upsert_session(make_session())
        rows = self.s.sessions()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], "sess-1")
        self.assertEqual(row["harness"], "claude")
        self.assertEqual(row["project"], "neva")
        self.assertEqual(row["branch"], "main")
        self.assertAlmostEqual(row["cost_usd"], 0.42)
        self.assertAlmostEqual(row["context_pct"], 12.5)
        self.assertEqual(row["risk_flags"], ["destructive-bash"])

    def test_upsert_same_id_updates_in_place_not_duplicated(self):
        self.s.upsert_session(make_session())
        self.s.upsert_session(make_session(cost_usd=1.10, risk_flags=[]))
        rows = self.s.sessions()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["cost_usd"], 1.10)
        self.assertEqual(rows[0]["risk_flags"], [])

    def test_upsert_with_partial_fields_preserves_other_columns(self):
        """Different ingest sources update different columns of the same session id; a later
        partial upsert must not clobber columns it does not mention."""
        self.s.upsert_session(make_session())
        self.s.upsert_session({"id": "sess-1", "cost_usd": 9.99})
        row = self.s.sessions()[0]
        self.assertAlmostEqual(row["cost_usd"], 9.99)
        self.assertEqual(row["project"], "neva")
        self.assertEqual(row["branch"], "main")
        self.assertEqual(row["risk_flags"], ["destructive-bash"])

    def test_sessions_ordered_by_last_activity_descending(self):
        self.s.upsert_session(make_session(id="a", last_activity="2026-10-05T09:00:00Z"))
        self.s.upsert_session(make_session(id="b", last_activity="2026-10-05T11:00:00Z"))
        rows = self.s.sessions()
        self.assertEqual([r["id"] for r in rows], ["b", "a"])

    @mock.patch.dict(os.environ, {"NEVA_TIMEZONE": "UTC"})  # the naive 11:00 below is 11:00Z
    def test_last_activity_only_moves_forward_and_empty_never_wins(self):
        self.s.upsert_session(make_session(last_activity="2026-10-05T10:05:00Z"))
        self.s.upsert_session({"id": "sess-1", "last_activity": "2026-10-05T09:00:00Z"})
        self.assertEqual(self.s.sessions()[0]["last_activity"], "2026-10-05T10:05:00Z")
        self.s.upsert_session({"id": "sess-1", "last_activity": ""})
        self.assertEqual(self.s.sessions()[0]["last_activity"], "2026-10-05T10:05:00Z")
        self.s.upsert_session({"id": "sess-1", "last_activity": "2026-10-05 11:00"})
        self.assertEqual(self.s.sessions()[0]["last_activity"], "2026-10-05T11:00")

    def test_missing_optional_fields_default_sanely(self):
        self.s.upsert_session({"id": "bare", "harness": "codex"})
        row = self.s.sessions()[0]
        self.assertEqual(row["project"], "")
        self.assertEqual(row["risk_flags"], [])
        self.assertEqual(row["cost_usd"], 0)


class ActivityInstantTests(unittest.TestCase):
    """Review 2 M4: last activity compared timestamp strings, so a UTC stamp and a local-offset
    stamp could move activity backwards in real time and sort sessions out of order."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"NEVA_TIMEZONE": "Etc/GMT-3"})  # UTC+3
        patcher.start()
        self.addCleanup(patcher.stop)
        self.s = store.Store(":memory:")
        self.addCleanup(self.s.close)

    def activity(self, *stamps, sid="sess-1"):
        for stamp in stamps:
            self.s.upsert_session({"id": sid, "last_activity": stamp})
        return {r["id"]: r["last_activity"] for r in self.s.sessions()}[sid]

    def test_the_same_instant_in_another_offset_is_not_a_move(self):
        self.assertEqual(self.activity("2026-10-08T10:00:00+00:00", "2026-10-08T13:00:00+03:00"),
                         "2026-10-08T10:00:00+00:00")

    def test_a_lexically_later_but_earlier_instant_never_wins(self):
        # 12:00+05:00 is 07:00 UTC, three hours before 10:00Z
        self.assertEqual(self.activity("2026-10-08T10:00:00Z", "2026-10-08T12:00:00+05:00"),
                         "2026-10-08T10:00:00Z")

    def test_a_lexically_earlier_but_later_instant_wins(self):
        self.assertEqual(self.activity("2026-10-08T12:00:00+05:00", "2026-10-08T09:00:00Z"),
                         "2026-10-08T09:00:00Z")

    def test_naive_times_are_read_in_the_configured_timezone(self):
        # 10:30 at UTC+3 is 07:30 UTC, so 08:00Z is later
        self.assertEqual(self.activity("2026-10-08 10:30", "2026-10-08T08:00:00Z"),
                         "2026-10-08T08:00:00Z")

    def test_rows_written_before_the_instant_column_are_backfilled_on_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cockpit.db")
            first = store.Store(path)
            first.upsert_session({"id": "old", "last_activity": "2026-10-08T09:00:00Z"})
            first.conn.execute("UPDATE sessions SET last_activity_at = NULL")
            first.conn.commit()
            first.close()
            reopened = store.Store(path)
            at = reopened.conn.execute("SELECT last_activity_at FROM sessions").fetchone()[0]
            reopened.close()
        self.assertEqual(at, store.parse_instant("2026-10-08T09:00:00Z"))

    def test_sessions_sort_by_instant_not_by_string(self):
        self.s.upsert_session({"id": "a", "last_activity": "2026-10-08T12:00:00+05:00"})
        self.s.upsert_session({"id": "b", "last_activity": "2026-10-08T09:00:00Z"})
        self.s.upsert_session({"id": "c", "last_activity": ""})
        self.assertEqual([r["id"] for r in self.s.sessions()], ["b", "a", "c"])


class RiskFlagAccumulationTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(":memory:")

    def tearDown(self):
        self.s.close()

    def test_add_risk_flags_on_new_session_creates_row(self):
        self.s.add_risk_flags("new-sess", ["tool-error:Bash"])
        row = self.s.sessions()[0]
        self.assertEqual(row["id"], "new-sess")
        self.assertEqual(row["risk_flags"], ["tool-error:Bash"])

    def test_add_risk_flags_unions_and_dedupes_without_touching_other_columns(self):
        self.s.upsert_session(make_session(risk_flags=["a"]))
        self.s.add_risk_flags("sess-1", ["b", "a"])
        row = self.s.sessions()[0]
        self.assertEqual(row["risk_flags"], ["a", "b"])
        self.assertEqual(row["project"], "neva")


class IngestOffsetTests(unittest.TestCase):
    def setUp(self):
        self.s = store.Store(":memory:")

    def tearDown(self):
        self.s.close()

    def test_unknown_path_returns_none(self):
        self.assertIsNone(self.s.get_offset("/nowhere/costs.jsonl"))

    def test_set_then_get_round_trips(self):
        self.s.set_offset("/data/costs.jsonl", 128, 1696500000.0, 512)
        got = self.s.get_offset("/data/costs.jsonl")
        self.assertEqual(got["offset"], 128)
        self.assertEqual(got["mtime"], 1696500000.0)
        self.assertEqual(got["size"], 512)

    def test_set_again_overwrites_not_duplicates(self):
        self.s.set_offset("/data/costs.jsonl", 100, 1.0, 100)
        self.s.set_offset("/data/costs.jsonl", 200, 2.0, 200)
        got = self.s.get_offset("/data/costs.jsonl")
        self.assertEqual(got["offset"], 200)
        count = self.s.conn.execute(
            "SELECT COUNT(*) FROM ingest_offsets WHERE path = ?", ("/data/costs.jsonl",)).fetchone()[0]
        self.assertEqual(count, 1)


class DefaultDbPathTests(unittest.TestCase):
    def test_default_db_path_lives_under_the_hooks_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("NEVA_DATA_DIR")
            os.environ["NEVA_DATA_DIR"] = d
            try:
                path = store.default_db_path()
                self.assertTrue(str(path).startswith(d))
            finally:
                if old is None:
                    os.environ.pop("NEVA_DATA_DIR", None)
                else:
                    os.environ["NEVA_DATA_DIR"] = old


if __name__ == "__main__":
    unittest.main()
