import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from neva_cockpit import ingest  # noqa: E402
from neva_cockpit.store import Store  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def cost_row(session_id):
    return json.dumps({"session_id": session_id, "estimated_cost_usd": 1.0}) + "\n"


class CostsJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.path = os.path.join(self.tmp.name, "costs.jsonl")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_valid_rows_land_as_sessions(self):
        rows = [
            {"timestamp": "2026-10-05T10:00:00", "session_id": "s1", "project": "neva",
             "model": "sonnet", "estimated_cost_usd": 1.5},
            {"timestamp": "2026-10-05T10:05:00", "session_id": "s2", "project": "neva",
             "model": "opus", "estimated_cost_usd": 2.25},
        ]
        write(self.path, "\n".join(json.dumps(r) for r in rows) + "\n")
        count = ingest.ingest_costs(self.store, self.path)
        self.assertEqual(count, 2)
        by_id = {r["id"]: r for r in self.store.sessions()}
        self.assertAlmostEqual(by_id["s1"]["cost_usd"], 1.5)
        self.assertAlmostEqual(by_id["s2"]["cost_usd"], 2.25)

    def test_malformed_line_is_skipped_valid_lines_on_either_side_still_land(self):
        good1 = json.dumps({"session_id": "s1", "project": "p", "estimated_cost_usd": 1.0,
                             "timestamp": "t1"})
        bad = "{not json"
        good2 = json.dumps({"session_id": "s2", "project": "p", "estimated_cost_usd": 2.0,
                             "timestamp": "t2"})
        write(self.path, "\n".join([good1, bad, good2]) + "\n")
        count = ingest.ingest_costs(self.store, self.path)
        self.assertEqual(count, 2)
        ids = {r["id"] for r in self.store.sessions()}
        self.assertEqual(ids, {"s1", "s2"})

    def test_rerunning_on_unchanged_file_inserts_zero_new_rows(self):
        write(self.path, json.dumps({"session_id": "s1", "project": "p",
                                      "estimated_cost_usd": 1.0, "timestamp": "t1"}) + "\n")
        first = ingest.ingest_costs(self.store, self.path)
        self.assertEqual(first, 1)
        second = ingest.ingest_costs(self.store, self.path)
        self.assertEqual(second, 0)
        self.assertEqual(len(self.store.sessions()), 1)

    def test_appending_more_rows_only_ingests_the_new_ones(self):
        write(self.path, json.dumps({"session_id": "s1", "project": "p",
                                      "estimated_cost_usd": 1.0, "timestamp": "t1"}) + "\n")
        ingest.ingest_costs(self.store, self.path)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session_id": "s2", "project": "p",
                                  "estimated_cost_usd": 2.0, "timestamp": "t2"}) + "\n")
        count = ingest.ingest_costs(self.store, self.path)
        self.assertEqual(count, 1)
        self.assertEqual(len(self.store.sessions()), 2)

    def test_missing_file_is_a_no_op_not_an_error(self):
        count = ingest.ingest_costs(self.store, os.path.join(self.tmp.name, "nope.jsonl"))
        self.assertEqual(count, 0)

    def test_valid_json_with_a_wrong_type_is_rejected_and_never_blocks_later_runs(self):
        """Review H7: a cost of "bad-value" raised before the offset was saved, so every run
        retried that row, stopped again, and nothing after it ever landed."""
        rows = [
            {"session_id": "s1", "project": "p", "estimated_cost_usd": 1.0, "timestamp": "t1"},
            {"session_id": "s2", "project": "p", "estimated_cost_usd": "bad-value",
             "timestamp": "t2"},
            {"session_id": "s3", "project": 7, "estimated_cost_usd": 1.0, "timestamp": "t3"},
            {"session_id": "s4", "project": "p", "estimated_cost_usd": 3.0, "timestamp": "t4"},
        ]
        write(self.path, "\n".join(json.dumps(r) for r in rows) + "\n")
        rejected = []
        count = ingest.ingest_costs(self.store, self.path, rejected=rejected)
        self.assertEqual(count, 2)
        self.assertEqual({r["id"] for r in self.store.sessions()}, {"s1", "s4"})
        self.assertEqual([r["line"] for r in rejected], [2, 3])
        self.assertIn("estimated_cost_usd", rejected[0]["reason"])
        self.assertIn("project", rejected[1]["reason"])
        self.assertIsNotNone(self.store.get_offset(self.path), "the offset never advanced")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session_id": "s5", "estimated_cost_usd": 0.5}) + "\n")
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)
        self.assertIn("s5", {r["id"] for r in self.store.sessions()})

    def test_numbers_that_cannot_be_a_float_are_rejected_and_the_next_run_advances(self):
        """Review 2 M1: a JSON integer too large for a float raised OverflowError, which the
        per-row handler did not catch, so the offset never advanced and every retry stopped."""
        lines = [json.dumps({"session_id": "s1", "estimated_cost_usd": 1.0}),
                 '{"session_id": "s-huge", "estimated_cost_usd": 1' + "0" * 400 + "}",
                 '{"session_id": "s-nan", "estimated_cost_usd": NaN}',
                 '{"session_id": "s-inf", "estimated_cost_usd": -Infinity}',
                 json.dumps({"session_id": "s2", "estimated_cost_usd": 2.0})]
        write(self.path, "\n".join(lines) + "\n")
        rejected = []
        self.assertEqual(ingest.ingest_costs(self.store, self.path, rejected=rejected), 2)
        self.assertEqual({r["id"] for r in self.store.sessions()}, {"s1", "s2"})
        self.assertEqual([r["line"] for r in rejected], [2, 3, 4])
        self.assertTrue(all("estimated_cost_usd" in r["reason"] for r in rejected))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session_id": "s3", "estimated_cost_usd": 3.0}) + "\n")
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)
        self.assertIn("s3", {r["id"] for r in self.store.sessions()})

    def test_a_database_failure_is_not_swallowed_as_a_bad_row(self):
        write(self.path, json.dumps({"session_id": "s1", "estimated_cost_usd": 1.0}) + "\n")
        with mock.patch.object(self.store, "upsert_session",
                               side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                ingest.ingest_costs(self.store, self.path)
        self.assertIsNone(self.store.get_offset(self.path),
                          "the offset advanced past a row that never landed")


class ReplacedFileTests(unittest.TestCase):
    """Review 2 M2: only shrinkage reset the offset, so a consumed file replaced by different
    content of the same size (or rotated and regrown past the old size) was skipped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.path = os.path.join(self.tmp.name, "costs.jsonl")
        write(self.path, cost_row("aa"))
        os.utime(self.path, (1_000_000, 1_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def ids(self):
        return {r["id"] for r in self.store.sessions()}

    def test_same_size_replacement_by_a_new_file_is_read_from_the_start(self):
        fresh = self.path + ".new"
        write(fresh, cost_row("bb"))
        self.assertEqual(os.path.getsize(fresh), os.path.getsize(self.path))
        os.replace(fresh, self.path)
        os.utime(self.path, (2_000_000, 2_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)
        self.assertEqual(self.ids(), {"aa", "bb"})

    def test_same_size_rewrite_in_place_is_read_from_the_start(self):
        with open(self.path, "w", encoding="utf-8") as fh:  # same inode, new bytes
            fh.write(cost_row("cc"))
        os.utime(self.path, (2_000_000, 2_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)
        self.assertEqual(self.ids(), {"aa", "cc"})

    def test_copy_truncate_rotation_that_regrew_past_the_old_size(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(cost_row("dd") + cost_row("ee") + cost_row("ff"))
        os.utime(self.path, (2_000_000, 2_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 3)
        self.assertEqual(self.ids(), {"aa", "dd", "ee", "ff"})

    def test_rotation_to_a_new_file_that_regrew_past_the_old_size(self):
        os.rename(self.path, self.path + ".1")
        write(self.path, cost_row("gg") + cost_row("hh"))
        os.utime(self.path, (2_000_000, 2_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 2)
        self.assertEqual(self.ids(), {"aa", "gg", "hh"})

    def test_a_plain_append_still_reads_only_the_new_line(self):
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(cost_row("ii"))
        os.utime(self.path, (2_000_000, 2_000_000))
        self.assertEqual(ingest.ingest_costs(self.store, self.path), 1)
        self.assertEqual(self.ids(), {"aa", "ii"})


class ObservationsJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.path = os.path.join(self.tmp.name, "observations.jsonl")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_tool_error_event_adds_a_risk_flag(self):
        rec = {"event": "tool_error", "tool": "Bash", "session": "s1", "project_name": "neva"}
        write(self.path, json.dumps(rec) + "\n")
        ingest.ingest_observations(self.store, self.path)
        row = self.store.sessions()[0]
        self.assertIn("tool-error:Bash", row["risk_flags"])

    def test_destructive_bash_command_adds_a_risk_flag(self):
        rec = {"event": "tool_start", "tool": "Bash", "session": "s1", "project_name": "neva",
               "input": {"command": "rm -rf /tmp/x"}}
        write(self.path, json.dumps(rec) + "\n")
        ingest.ingest_observations(self.store, self.path)
        row = self.store.sessions()[0]
        self.assertTrue(any(f.startswith("destructive-bash") for f in row["risk_flags"]))

    def test_benign_bash_command_adds_no_risk_flag(self):
        rec = {"event": "tool_start", "tool": "Bash", "session": "s1", "project_name": "neva",
               "input": {"command": "ls -la"}}
        write(self.path, json.dumps(rec) + "\n")
        ingest.ingest_observations(self.store, self.path)
        row = self.store.sessions()[0]
        self.assertEqual(row["risk_flags"], [])

    def test_a_long_destructive_command_cut_by_the_hook_is_still_flagged(self):
        """Review 3 M2: observe truncates input at 5000 characters, the truncated JSON no
        longer parses, and the command was treated as empty, so it was never flagged."""
        from neva_hooks import observe
        command = "rm -rf build && " + "echo filler; " * 500
        self.assertGreater(len(command), 6000)
        rec = {"event": "tool_start", "tool": "Bash", "session": "s1",
               "input": observe._truncate({"command": command})}
        self.assertIn("[truncated", rec["input"])
        write(self.path, json.dumps(rec) + "\n")
        ingest.ingest_observations(self.store, self.path)
        flags = self.store.sessions()[0]["risk_flags"]
        self.assertIn("destructive-bash:rm-rf", flags)
        self.assertIn("bash-input-truncated", flags)

    def test_a_long_benign_command_is_marked_truncated_never_silently_clean(self):
        from neva_hooks import observe
        rec = {"event": "tool_start", "tool": "Bash", "session": "s1",
               "input": observe._truncate({"command": "echo filler; " * 500})}
        write(self.path, json.dumps(rec) + "\n")
        ingest.ingest_observations(self.store, self.path)
        self.assertEqual(self.store.sessions()[0]["risk_flags"], ["bash-input-truncated"])

    def test_malformed_line_is_skipped_valid_lines_on_either_side_still_land(self):
        good1 = json.dumps({"event": "tool_error", "tool": "Bash", "session": "s1"})
        bad = "not even close to json{{{"
        good2 = json.dumps({"event": "tool_error", "tool": "Write", "session": "s2"})
        write(self.path, "\n".join([good1, bad, good2]) + "\n")
        ingest.ingest_observations(self.store, self.path)
        by_id = {r["id"]: r for r in self.store.sessions()}
        self.assertIn("tool-error:Bash", by_id["s1"]["risk_flags"])
        self.assertIn("tool-error:Write", by_id["s2"]["risk_flags"])

    def test_valid_json_with_a_wrong_type_is_rejected_and_neighbours_land(self):
        rows = [{"event": "tool_error", "tool": "Bash", "session": "s1"},
                {"event": "tool_error", "tool": "Bash", "session": ["not", "a", "string"]},
                {"event": "tool_error", "tool": {"x": 1}, "session": "s2"},
                {"event": "tool_error", "tool": "Write", "session": "s3"}]
        write(self.path, "\n".join(json.dumps(r) for r in rows) + "\n")
        rejected = []
        ingest.ingest_observations(self.store, self.path, rejected=rejected)
        self.assertEqual({r["id"] for r in self.store.sessions()}, {"s1", "s3"})
        self.assertEqual([r["line"] for r in rejected], [2, 3])

    def test_rerunning_on_unchanged_file_inserts_zero_new_rows(self):
        write(self.path, json.dumps({"event": "tool_error", "tool": "Bash", "session": "s1"}) + "\n")
        ingest.ingest_observations(self.store, self.path)
        before = len(self.store.sessions())
        ingest.ingest_observations(self.store, self.path)
        after = len(self.store.sessions())
        self.assertEqual(before, after)
        self.assertEqual(after, 1)


class SessionSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_header_fields_land_in_the_session_row(self):
        path = os.path.join(self.tmp.name, "2026-10-05-abcd1234-session.tmp")
        text = (
            "# Session: 2026-10-05\n"
            "**Date:** 2026-10-05\n"
            "**Started:** 10:00\n"
            "**Last Updated:** 10:30\n"
            "**Project:** neva\n"
            "**Branch:** feat/cockpit\n"
            "**Worktree:** /tmp/neva\n"
            "**Repo:** /tmp/neva/.git\n"
            "**Session:** full-session-id-1\n"
            "\n---\n"
        )
        write(path, text)
        ingest.ingest_session_files(self.store, self.tmp.name)
        row = self.store.sessions()[0]
        self.assertEqual(row["id"], "full-session-id-1")
        self.assertEqual(row["harness"], "claude")
        self.assertEqual(row["project"], "neva")
        self.assertEqual(row["branch"], "feat/cockpit")

    def test_rerunning_on_unchanged_file_inserts_zero_new_rows(self):
        path = os.path.join(self.tmp.name, "2026-10-05-abcd1234-session.tmp")
        write(path, "**Session:** full-session-id-1\n**Project:** neva\n")
        ingest.ingest_session_files(self.store, self.tmp.name)
        before = len(self.store.sessions())
        ingest.ingest_session_files(self.store, self.tmp.name)
        after = len(self.store.sessions())
        self.assertEqual(before, after)
        self.assertEqual(after, 1)

    def test_file_without_a_session_id_is_skipped_without_erroring(self):
        path = os.path.join(self.tmp.name, "2026-10-05-xxxx-session.tmp")
        write(path, "**Project:** neva\n")
        ingest.ingest_session_files(self.store, self.tmp.name)
        self.assertEqual(self.store.sessions(), [])


class CrossSourceMergeTests(unittest.TestCase):
    """Review M4: a sparse cost row must not blank what another source already wrote, and an
    older timestamp from one source must not roll last activity backwards."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.sessions = os.path.join(self.tmp.name, "sessions")
        self.costs = os.path.join(self.tmp.name, "costs.jsonl")
        write(os.path.join(self.sessions, "2026-10-05-abcd-session.tmp"),
              "**Date:** 2026-10-05\n**Started:** 10:00\n**Last Updated:** 10:30\n"
              "**Project:** neva\n**Branch:** main\n**Session:** s1\n")
        ingest.ingest_session_files(self.store, self.sessions)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_sparse_cost_row_keeps_project_activity_and_branch(self):
        write(self.costs, json.dumps({"session_id": "s1", "estimated_cost_usd": 2.5}) + "\n")
        self.assertEqual(ingest.ingest_costs(self.store, self.costs), 1)
        row = self.store.sessions()[0]
        self.assertEqual(row["project"], "neva")
        self.assertEqual(row["branch"], "main")
        self.assertEqual(row["last_activity"], "2026-10-05T10:30")
        self.assertAlmostEqual(row["cost_usd"], 2.5)

    def test_cost_row_without_a_cost_keeps_the_known_cost(self):
        write(self.costs, json.dumps({"session_id": "s1", "estimated_cost_usd": 2.5}) + "\n"
              + json.dumps({"session_id": "s1", "timestamp": "2026-10-05T10:40:00"}) + "\n")
        ingest.ingest_costs(self.store, self.costs)
        self.assertAlmostEqual(self.store.sessions()[0]["cost_usd"], 2.5)

    def test_an_older_timestamp_never_rolls_activity_back(self):
        write(self.costs, json.dumps({"session_id": "s1", "estimated_cost_usd": 1.0,
                                      "timestamp": "2026-10-05T10:05:00"}) + "\n")
        ingest.ingest_costs(self.store, self.costs)
        self.assertEqual(self.store.sessions()[0]["last_activity"], "2026-10-05T10:30")

    def test_a_newer_timestamp_moves_activity_forward(self):
        write(self.costs, json.dumps({"session_id": "s1", "estimated_cost_usd": 1.0,
                                      "timestamp": "2026-10-05T11:00:00"}) + "\n")
        ingest.ingest_costs(self.store, self.costs)
        self.assertEqual(self.store.sessions()[0]["last_activity"], "2026-10-05T11:00:00")


class CodexSessionTests(unittest.TestCase):
    """Review M1: legacy session_meta records carry only payload.id (Codex's own deserializer
    falls back to it), and last activity must come from the file, not from ingest time."""

    HISTORIC = 1704196800  # 2024-01-02T12:00:00Z

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.root = os.path.join(self.tmp.name, "sessions")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def rollout(self, name, first_line):
        path = os.path.join(self.root, "2024", "01", "02", name)
        write(path, json.dumps(first_line) + "\n" + json.dumps({"type": "event_msg"}) + "\n")
        os.utime(path, (self.HISTORIC, self.HISTORIC))
        return path

    def test_legacy_id_only_record_lands_under_its_thread_id(self):
        self.rollout("rollout-legacy.jsonl", {"type": "session_meta", "payload": {
            "id": "legacy-thread", "timestamp": "2024-01-02T11:00:00Z", "cwd": "/w/legacy"}})
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 1)
        row = self.store.sessions()[0]
        self.assertEqual((row["id"], row["harness"], row["project"]),
                         ("legacy-thread", "codex", "legacy"))

    def test_pre_payload_record_lands(self):
        self.rollout("rollout-old.jsonl", {"id": "old-thread",
                                           "timestamp": "2024-01-02T11:00:00Z"})
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 1)
        self.assertEqual(self.store.sessions()[0]["id"], "old-thread")

    def test_modern_record_keys_on_session_id(self):
        self.rollout("rollout-modern.jsonl", {"type": "session_meta", "payload": {
            "session_id": "root-thread", "id": "child-thread",
            "timestamp": "2024-01-02T11:00:00Z", "cwd": "/w/modern"}})
        ingest.ingest_codex_sessions(self.store, self.root)
        self.assertEqual(self.store.sessions()[0]["id"], "root-thread")

    def test_last_activity_is_the_file_mtime_not_now(self):
        self.rollout("rollout-modern.jsonl", {"type": "session_meta", "payload": {
            "session_id": "s", "timestamp": "2024-01-02T11:00:00Z", "cwd": "/w/x"}})
        ingest.ingest_codex_sessions(self.store, self.root)
        row = self.store.sessions()[0]
        self.assertTrue(row["last_activity"].startswith("2024-01-0"), row["last_activity"])
        self.assertEqual(row["started_at"], "2024-01-02T11:00:00Z")

    def test_repeat_ingest_is_a_no_op(self):
        self.rollout("rollout-legacy.jsonl", {"type": "session_meta", "payload": {
            "id": "legacy-thread", "timestamp": "2024-01-02T11:00:00Z"}})
        ingest.ingest_codex_sessions(self.store, self.root)
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 0)
        self.assertEqual(len(self.store.sessions()), 1)

    def test_a_first_line_still_being_written_is_retried_later(self):
        path = os.path.join(self.root, "rollout-partial.jsonl")
        write(path, '{"type": "session_meta", "payload": {"id": "late"')
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 0)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(', "timestamp": "2024-01-02T11:00:00Z"}}\n')
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 1)
        self.assertEqual(self.store.sessions()[0]["id"], "late")


class HookErrorRetentionTests(unittest.TestCase):
    """Review M3: hook errors were read, their offset advanced, and the result was discarded,
    so the cockpit never showed one. They are now kept in the store for every view."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.log = os.path.join(self.tmp.name, "hooks.log")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_hook_errors_survive_the_offset_advancing(self):
        write(self.log, "[info] fine\n[error] session_start: boom\n")
        self.assertEqual(ingest.ingest_hooks_log(self.store, self.log),
                         ["[error] session_start: boom"])
        self.assertEqual(ingest.ingest_hooks_log(self.store, self.log), [])
        notes = self.store.recent_notes("hook-error")
        self.assertEqual([n["detail"] for n in notes], ["[error] session_start: boom"])

    def test_notes_are_capped_newest_first(self):
        self.store.add_notes("hook-error", [f"[error] {i}" for i in range(300)])
        notes = self.store.recent_notes("hook-error", limit=500)
        self.assertEqual(len(notes), self.store.NOTES_KEPT)
        self.assertEqual(notes[0]["detail"], "[error] 299")


class FailingNotesConnection:
    """Wraps the store's sqlite connection and fails the first write into ingest_notes, the
    way a locked or full database would, then behaves normally."""

    def __init__(self, conn):
        self._conn = conn
        self.failed = False

    def _check(self, sql):
        if not self.failed and "INSERT INTO ingest_notes" in sql:
            self.failed = True
            raise sqlite3.OperationalError("database is locked (injected)")

    def execute(self, sql, *args):
        self._check(sql)
        return self._conn.execute(sql, *args)

    def executemany(self, sql, *args):
        self._check(sql)
        return self._conn.executemany(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class NotesBeforeOffsetTests(unittest.TestCase):
    """Review 2 M3: offsets advanced before hook errors and rejection notes were stored, so a
    failure between the two lost the notes for good. Persist first, then advance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        env = {"HOME": root, "NEVA_DATA_DIR": os.path.join(root, "data"),
               "NEVA_STATE_DIR": os.path.join(root, "state"),
               "NEVA_CONFIG": os.path.join(root, "none.env")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("NEVA_METRICS_DIR", "NEVA_OBSERVATIONS_DIR"):
            os.environ.pop(name, None)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.data = env["NEVA_DATA_DIR"]

    def run_failing_then_retry(self):
        real = self.store.conn
        self.store.conn = FailingNotesConnection(real)
        with self.assertRaises(sqlite3.OperationalError):
            ingest.ingest_all(self.store)
        self.assertTrue(self.store.conn.failed, "the injected failure never fired")
        self.store.conn = real
        ingest.ingest_all(self.store)
        ingest.ingest_all(self.store)

    def test_a_hook_error_is_kept_exactly_once_after_a_failed_save(self):
        write(os.path.join(self.data, "hooks.log"), "[error] stop: boom\n")
        self.run_failing_then_retry()
        self.assertEqual([n["detail"] for n in self.store.recent_notes("hook-error")],
                         ["[error] stop: boom"])

    def test_a_rejected_row_is_kept_exactly_once_after_a_failed_save(self):
        write(os.path.join(self.data, "metrics", "costs.jsonl"),
              json.dumps({"session_id": "good", "estimated_cost_usd": 1.0}) + "\n"
              + json.dumps({"session_id": "bad", "estimated_cost_usd": "x"}) + "\n")
        self.run_failing_then_retry()
        notes = [n["detail"] for n in self.store.recent_notes("rejected-row")]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("line 2: estimated_cost_usd", notes[0])
        self.assertEqual({r["id"] for r in self.store.sessions()}, {"good"})


class MixedSourceActivityTests(unittest.TestCase):
    """Review 2 M4: a codex rollout's local-offset mtime against a UTC cost stamp."""

    HISTORIC = 1704196800  # 2024-01-02T12:00:00Z

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "sessions")
        path = os.path.join(self.root, "rollout-x.jsonl")
        write(path, json.dumps({"type": "session_meta", "payload": {
            "id": "x", "timestamp": "2024-01-02T10:00:00Z", "cwd": "/w/x"}}) + "\n")
        os.utime(path, (self.HISTORIC, self.HISTORIC))
        self.costs = os.path.join(self.tmp.name, "costs.jsonl")

    def run_both(self, timezone, cost_stamp):
        with mock.patch.dict(os.environ, {"NEVA_TIMEZONE": timezone}):
            store = Store(":memory:")
            self.addCleanup(store.close)
            ingest.ingest_codex_sessions(store, self.root)
            write(self.costs, json.dumps({"session_id": "x", "estimated_cost_usd": 1.0,
                                          "timestamp": cost_stamp}) + "\n")
            ingest.ingest_costs(store, self.costs)
            return store.sessions()[0]["last_activity"]

    def test_a_later_utc_cost_beats_an_earlier_local_codex_mtime(self):
        # codex mtime renders as 15:00+03:00 (12:00Z); the cost at 13:00Z is later
        self.assertEqual(self.run_both("Etc/GMT-3", "2024-01-02T13:00:00Z"),
                         "2024-01-02T13:00:00Z")

    def test_an_earlier_utc_cost_never_beats_a_later_local_codex_mtime(self):
        # codex mtime renders as 07:00-05:00 (12:00Z); the cost at 11:00Z is earlier
        self.assertEqual(self.run_both("Etc/GMT+5", "2024-01-02T11:00:00Z"),
                         "2024-01-02T07:00:00-05:00")


class RealSizeCodexTests(unittest.TestCase):
    """Review 3 H1: current Codex puts the whole system prompt (base_instructions) in the
    session_meta line, 18 KB to 42 KB on a real machine. A 4 KB read found no newline, so every
    real rollout was marked read with no session and no note."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.root = os.path.join(self.tmp.name, "sessions")

    def rollout(self, name, sid, prompt_chars):
        meta = {"timestamp": "2026-10-09T08:00:00Z", "type": "session_meta", "payload": {
            "session_id": sid, "id": sid, "timestamp": "2026-10-09T08:00:00Z",
            "cwd": "/w/" + sid, "base_instructions": {"text": "x" * prompt_chars}}}
        path = os.path.join(self.root, "2026", "10", "09", name)
        write(path, json.dumps(meta) + "\n" + json.dumps({"type": "event_msg"}) + "\n")
        return path

    def test_a_real_size_session_meta_line_is_ingested(self):
        self.rollout("rollout-small.jsonl", "small", 100)
        self.rollout("rollout-real.jsonl", "real", 42_000)
        self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root), 2)
        self.assertEqual({r["id"] for r in self.store.sessions()}, {"small", "real"})

    def test_a_first_line_over_the_cap_is_a_rejected_row_not_a_silent_read(self):
        path = self.rollout("rollout-huge.jsonl", "huge", 20_000)
        with mock.patch.object(ingest, "CODEX_FIRST_LINE_MAX", 4096):  # the old cap
            rejected = []
            self.assertEqual(ingest.ingest_codex_sessions(self.store, self.root, rejected), 0)
            notes = [n["detail"] for n in self.store.recent_notes("rejected-row")]
            self.assertEqual(len(notes), 1, notes)
            self.assertIn(path, notes[0])
            self.assertIn("4096", notes[0])
            self.assertEqual(rejected[0]["path"], path)
            # the file changing again does not bury the note under a silent re-read, and
            # does not repeat it either
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "event_msg"}) + "\n")
            ingest.ingest_codex_sessions(self.store, self.root)
            self.assertEqual(len(self.store.recent_notes("rejected-row")), 1)
        self.assertEqual(self.store.sessions(), [])

    def test_a_first_line_that_is_not_a_session_record_is_noted(self):
        path = os.path.join(self.root, "rollout-odd.jsonl")
        write(path, json.dumps({"type": "response_item"}) + "\n")
        ingest.ingest_codex_sessions(self.store, self.root)
        notes = [n["detail"] for n in self.store.recent_notes("rejected-row")]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("session_meta", notes[0])


class TracebackHookErrorTests(unittest.TestCase):
    """Review 3 M1: log_exception writes the traceback as indented continuation lines, and
    the panel kept only the first: always "Traceback (most recent call last):"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"NEVA_DATA_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def failing_vault_write(self):
        raise PermissionError("cannot write vault note: 03 People/Jane Doe.md")

    def test_the_panel_names_the_exception_and_where_it_was_raised(self):
        from neva_cockpit import hooks_common
        try:
            self.failing_vault_write()
        except PermissionError:
            hooks_common.log_exception("stop")
        hooks_common.log("[info] unrelated line after it")
        errors = ingest.ingest_hooks_log(self.store)
        self.assertEqual(len(errors), 1, errors)
        note = errors[0]
        self.assertIn("[error] stop: PermissionError: cannot write vault note", note)
        self.assertIn("test_ingest.py", note)
        self.assertIn("failing_vault_write", note)
        self.assertNotIn("Traceback (most recent call last)", note)
        self.assertLessEqual(len(note), ingest.HOOK_ERROR_MAX_CHARS)
        self.assertEqual([n["detail"] for n in self.store.recent_notes("hook-error")], [note])

    def test_a_long_message_is_bounded(self):
        from neva_cockpit import hooks_common
        try:
            raise ValueError("y" * 5000)
        except ValueError:
            hooks_common.log_exception("observe")
        note = ingest.ingest_hooks_log(self.store)[0]
        self.assertLessEqual(len(note), ingest.HOOK_ERROR_MAX_CHARS)
        self.assertIn("ValueError: yyy", note)

    def test_a_single_line_error_is_kept_as_written(self):
        write(os.path.join(self.tmp.name, "hooks.log"), "2026-10-09 10:00:00 [error] x: boom\n")
        self.assertEqual(ingest.ingest_hooks_log(self.store),
                         ["2026-10-09 10:00:00 [error] x: boom"])


class IngestAllTests(unittest.TestCase):
    """Review M6: the old smoke test redirected only NEVA_DATA_DIR (so it could scan the real
    ~/.codex) and accepted any dict, even with every source call removed. This one isolates
    HOME and every source path, plants one record per source, and asserts rows, flags and
    counters; its negative control removes one source call and shows the check failing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        env = {"HOME": root, "NEVA_DATA_DIR": os.path.join(root, "data"),
               "NEVA_STATE_DIR": os.path.join(root, "state"),
               "NEVA_CONFIG": os.path.join(root, "none.env")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("NEVA_METRICS_DIR", "NEVA_OBSERVATIONS_DIR", "XDG_DATA_HOME",
                     "XDG_STATE_HOME"):
            os.environ.pop(name, None)
        data = env["NEVA_DATA_DIR"]
        write(os.path.join(data, "sessions", "2026-10-08-aaaa-session.tmp"),
              "**Date:** 2026-10-08\n**Last Updated:** 09:00\n**Project:** summary-proj\n"
              "**Branch:** main\n**Session:** s-summary\n")
        write(os.path.join(data, "metrics", "costs.jsonl"),
              json.dumps({"session_id": "s-cost", "estimated_cost_usd": 2.5,
                          "project": "cost-proj", "timestamp": "2026-10-08T09:05:00"}) + "\n"
              + json.dumps({"session_id": "s-bad", "estimated_cost_usd": "bad-value"}) + "\n")
        write(os.path.join(data, "observations", "proj", "observations.jsonl"),
              json.dumps({"event": "tool_error", "tool": "Bash", "session": "s-obs"}) + "\n"
              + json.dumps({"event": "tool_start", "tool": "Bash", "session": "s-obs",
                            "input": {"command": "rm -rf build"}}) + "\n")
        write(os.path.join(root, ".codex", "sessions", "2026", "10", "08", "rollout-a.jsonl"),
              json.dumps({"type": "session_meta", "payload": {
                  "id": "s-codex", "timestamp": "2026-10-08T08:00:00Z", "cwd": "/w/codex-proj"}})
              + "\n")
        write(os.path.join(data, "hooks.log"), "[info] ok\n[error] stop: boom\n")

    def check(self, result, store):
        self.assertEqual(result["session_files"], 1)
        self.assertEqual(result["costs"], 1)
        self.assertEqual(result["observations"], 2)
        self.assertEqual(result["codex_sessions"], 1)
        self.assertEqual(result["hook_errors"], ["[error] stop: boom"])
        self.assertEqual([r["line"] for r in result["rejected"]], [2])
        rows = {r["id"]: r for r in store.sessions()}
        self.assertEqual(set(rows), {"s-summary", "s-cost", "s-obs", "s-codex"})
        self.assertEqual(rows["s-summary"]["project"], "summary-proj")
        self.assertAlmostEqual(rows["s-cost"]["cost_usd"], 2.5)
        self.assertEqual(rows["s-obs"]["risk_flags"],
                         ["tool-error:Bash", "destructive-bash:rm-rf"])
        self.assertEqual((rows["s-codex"]["harness"], rows["s-codex"]["project"]),
                         ("codex", "codex-proj"))
        self.assertEqual([n["detail"] for n in store.recent_notes("hook-error")],
                         ["[error] stop: boom"])

    def test_every_source_lands_from_an_isolated_home(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        self.check(ingest.ingest_all(store), store)
        again = ingest.ingest_all(store)
        self.assertEqual((again["session_files"], again["costs"], again["observations"],
                          again["codex_sessions"], again["hook_errors"]), (0, 0, 0, 0, []))

    def test_negative_control_a_removed_source_call_fails_the_check(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        with mock.patch.object(ingest, "ingest_codex_sessions", return_value=0):
            result = ingest.ingest_all(store)
        with self.assertRaises(AssertionError):
            self.check(result, store)


if __name__ == "__main__":
    unittest.main()
