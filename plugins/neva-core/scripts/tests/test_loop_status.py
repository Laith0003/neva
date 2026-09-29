#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Tests for loop_status.py against fixture transcripts in a temp HOME.

Run:  python3 plugins/neva-core/scripts/tests/test_loop_status.py
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

sys.path.insert(0, support.SCRIPTS)
import loop_status as ls  # noqa: E402

NOW = "2026-09-29T12:00:00.000Z"


def assistant_tool(ts, tid, name, inp):
    return {"type": "assistant", "timestamp": ts, "sessionId": "sess-1",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def tool_result(ts, tid):
    return {"type": "user", "timestamp": ts, "sessionId": "sess-1",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-loop-test-")
        self.projects = os.path.join(self.sb.home, ".claude", "projects")

    def tearDown(self):
        self.sb.close()

    def transcript(self, slug, name, entries, raw_lines=()):
        d = os.path.join(self.projects, slug)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
            for line in raw_lines:
                fh.write(line + "\n")
        return p

    def status(self, *args):
        r = self.sb.run("loop_status.py", "--json", "--home", self.sb.home, "--now", NOW, *args)
        return r, (json.loads(r.stdout) if r.stdout.strip().startswith("{") and "--watch" not in args else None)


class TestSignals(LoopCase):
    def test_stale_bash_is_attention(self):
        self.transcript("-repo", "a.jsonl", [assistant_tool("2026-09-29T11:00:00Z", "t1", "Bash", {"command": "npm test"})])
        r, out = self.status()
        self.assertEqual(r.returncode, 0, r.stderr)
        s = out["sessions"][0]
        self.assertEqual(s["state"], "attention")
        sig = s["signals"][0]
        self.assertEqual((sig["type"], sig["command"], sig["ageSeconds"]), ("pending_bash_tool_result", "npm test", 3600))
        self.assertIn("Bash result appears stale", s["recommendedAction"])
        self.assertEqual(out["schemaVersion"], "neva.loop-status.v1")

    def test_answered_or_fresh_bash_is_ok(self):
        self.transcript("-repo", "a.jsonl", [
            assistant_tool("2026-09-29T10:00:00Z", "t1", "Bash", {"command": "ls"}),
            tool_result("2026-09-29T10:00:01Z", "t1"),
            assistant_tool("2026-09-29T11:59:00Z", "t2", "Bash", {"command": "sleep 5"}),
        ])
        r, out = self.status()
        s = out["sessions"][0]
        self.assertEqual(s["state"], "ok")
        self.assertEqual([t["toolUseId"] for t in s["pendingTools"]], ["t2"])

    def test_threshold_flag(self):
        self.transcript("-repo", "a.jsonl", [assistant_tool("2026-09-29T11:59:00Z", "t2", "Bash", {"command": "x"})])
        _, out = self.status("--bash-timeout-seconds", "30")
        self.assertEqual(out["sessions"][0]["signals"][0]["thresholdSeconds"], 30)

    def test_overdue_wakeup(self):
        self.transcript("-repo", "a.jsonl", [
            assistant_tool("2026-09-29T11:00:00Z", "w1", "ScheduleWakeup", {"delaySeconds": 600, "reason": "poll CI"}),
            tool_result("2026-09-29T11:00:01Z", "w1"),
        ])
        _, out = self.status()
        s = out["sessions"][0]
        self.assertEqual(s["signals"][0]["type"], "schedule_wakeup_overdue")
        self.assertEqual(s["signals"][0]["overdueSeconds"], 3000)
        self.assertEqual(s["latestWake"]["reason"], "poll CI")

    def test_wakeup_with_progress_after_due_is_ok(self):
        self.transcript("-repo", "a.jsonl", [
            assistant_tool("2026-09-29T11:00:00Z", "w1", "ScheduleWakeup", {"delaySeconds": 600}),
            tool_result("2026-09-29T11:00:01Z", "w1"),
            {"type": "assistant", "timestamp": "2026-09-29T11:10:30Z", "message": {"role": "assistant", "content": []}},
        ])
        _, out = self.status()
        self.assertEqual(out["sessions"][0]["state"], "ok")

    def test_wakeup_inside_grace_is_ok(self):
        self.transcript("-repo", "a.jsonl", [
            assistant_tool("2026-09-29T11:45:00Z", "w1", "ScheduleWakeup", {"delaySeconds": 600}),
            tool_result("2026-09-29T11:45:01Z", "w1"),
        ])
        _, out = self.status()
        self.assertEqual(out["sessions"][0]["state"], "ok", "due 11:55, grace x2 ends 12:05")

    def test_parse_errors_are_signalled(self):
        self.transcript("-repo", "a.jsonl", [], raw_lines=["{not json", "[1,2]"])
        _, out = self.status()
        s = out["sessions"][0]
        self.assertEqual(s["parseErrors"], 2)
        self.assertEqual(s["signals"][0]["type"], "transcript_parse_errors")

    def test_attention_sorts_first_and_limit_applies(self):
        a = self.transcript("-a", "ok.jsonl", [tool_result("2026-09-29T11:59:00Z", "x")])
        b = self.transcript("-b", "bad.jsonl", [assistant_tool("2026-09-29T09:00:00Z", "t", "Bash", {"command": "c"})])
        os.utime(a, (2000000000, 2000000000))
        os.utime(b, (1000000000, 1000000000))
        _, out = self.status()
        self.assertEqual([s["transcriptPath"] for s in out["sessions"]], [b, a])
        _, out = self.status("--limit", "1")
        self.assertEqual(len(out["sessions"]), 1)
        self.assertEqual(out["sessions"][0]["transcriptPath"], a, "limit keeps the newest by mtime")

    def test_direct_transcript_path(self):
        p = self.transcript("-x", "one.jsonl", [assistant_tool("2026-09-29T11:00:00Z", "t", "Bash", {"command": "c"})])
        r = self.sb.run("loop_status.py", "--json", "--now", NOW, "--transcript", p)
        out = json.loads(r.stdout)
        self.assertEqual(out["sessions"][0]["sessionId"], "sess-1")
        self.assertEqual(out["sessions"][0]["projectSlug"], "-x")


class TestCli(LoopCase):
    def test_exit_codes(self):
        r, _ = self.status("--exit-code")
        self.assertEqual(r.returncode, 0, "no transcripts, no errors")
        self.transcript("-repo", "a.jsonl", [assistant_tool("2026-09-29T11:00:00Z", "t1", "Bash", {"command": "c"})])
        r, _ = self.status("--exit-code")
        self.assertEqual(r.returncode, 2)
        r, _ = self.status()
        self.assertEqual(r.returncode, 0, "without --exit-code the status is informational")

    def test_text_output(self):
        r = self.sb.run("loop_status.py", "--home", self.sb.home, "--now", NOW)
        self.assertIn("No Claude transcript JSONL files found under", r.stdout)
        self.transcript("-repo", "a.jsonl", [assistant_tool("2026-09-29T11:00:00Z", "t1", "Bash", {"command": "c"})])
        r = self.sb.run("loop_status.py", "--home", self.sb.home, "--now", NOW)
        self.assertIn("Neva loop status (2026-09-29T12:00:00.000Z)", r.stdout)
        self.assertIn("[attention]", r.stdout)
        self.assertIn("signals: pending_bash_tool_result", r.stdout)

    def test_watch_count_emits_one_json_line_per_refresh(self):
        self.transcript("-repo", "a.jsonl", [tool_result("2026-09-29T11:59:00Z", "x")])
        r = self.sb.run("loop_status.py", "--json", "--home", self.sb.home, "--now", NOW, "--watch", "--watch-count",
                        "2", "--watch-interval-seconds", "0.05")
        lines = [x for x in r.stdout.splitlines() if x.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["schemaVersion"], "neva.loop-status.v1")

    def test_exit_code_watch_needs_count(self):
        r = self.sb.run("loop_status.py", "--watch", "--exit-code")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--exit-code with --watch requires --watch-count", r.stderr)

    def test_bad_flags_name_the_flag(self):
        for args, msg in ((["--limit", "0"], "--limit must be a positive"), (["--now", "tomorrow"], "--now must be"),
                          (["--bogus"], "Unknown option: --bogus"), (["--home"], "--home requires a value")):
            r = self.sb.run("loop_status.py", *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(msg, r.stderr)

    def test_write_dir_snapshots(self):
        self.transcript("-repo", "a.jsonl", [assistant_tool("2026-09-29T11:00:00Z", "t1", "Bash", {"command": "c"})])
        out_dir = self.sb.path("loops")
        r, _ = self.status("--write-dir", out_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out_dir, "index.json")) as fh:
            index = json.load(fh)
        self.assertEqual(index["schemaVersion"], "neva.loop-status.index.v1")
        self.assertEqual(index["sessions"][0]["signalTypes"], ["pending_bash_tool_result"])
        with open(index["sessions"][0]["snapshotPath"]) as fh:
            self.assertEqual(json.load(fh)["session"]["sessionId"], "sess-1")
        self.assertEqual([n for n in os.listdir(out_dir) if n.endswith(".tmp")], [])


class TestUnits(unittest.TestCase):
    def test_snapshot_names(self):
        self.assertEqual(ls.sanitize_snapshot_name("abc-123"), "abc-123")
        self.assertEqual(ls.sanitize_snapshot_name("a/b c"), "a_b_c")
        self.assertTrue(ls.sanitize_snapshot_name("CON").startswith("CON-"))
        self.assertTrue(ls.sanitize_snapshot_name("nul.txt").startswith("nul-"))
        long = ls.sanitize_snapshot_name("x" * 200)
        self.assertLessEqual(len(long), 61)
        used = set()
        a = ls.snapshot_path("/d", {"sessionId": "s", "transcriptPath": "/1"}, used)
        b = ls.snapshot_path("/d", {"sessionId": "s", "transcriptPath": "/2"}, used)
        self.assertNotEqual(a, b)

    def test_tool_extraction_shapes(self):
        e = {"tool_use": {"id": "a", "name": "Bash"}, "type": "tool_use", "id": "b", "name": "Read"}
        self.assertEqual({u["id"] for u in ls.extract_tool_uses(e)}, {"a", "b"})
        r = {"toolUseResult": {"tool_use_id": "a"}, "type": "tool_result", "tool_use_id": "b"}
        self.assertEqual(set(ls.extract_tool_result_ids(r)), {"a", "b"})

    def test_timestamps(self):
        self.assertEqual(ls.iso(ls.parse_timestamp("2026-01-01T00:00:00.1Z")), "2026-01-01T00:00:00.100Z")
        self.assertEqual(ls.iso(ls.parse_timestamp(1700000000000)), "2023-11-14T22:13:20.000Z")
        self.assertIsNone(ls.parse_timestamp("nope"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
