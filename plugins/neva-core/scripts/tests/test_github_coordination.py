#!/usr/bin/env python3
# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""Tests for github_coordination.py against a fake gh on PATH. No network, no real GitHub.

Run:  python3 plugins/neva-core/scripts/tests/test_github_coordination.py
"""
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402

sys.path.insert(0, support.SCRIPTS)
import github_coordination as gc  # noqa: E402

REPO = "octo/widgets"
MARK = "neva-coordination"


def block(state):
    return f"<!-- {MARK}:start -->\n```json\n{json.dumps(state, indent=2)}\n```\n<!-- {MARK}:end -->"


class GhCase(unittest.TestCase):
    def setUp(self):
        self.sb = support.Sandbox("neva-gc-test-")
        support.write_exe(os.path.join(self.sb.bin, "gh"), support.FAKE_GH)
        self.state_path = self.sb.path("gh-state.json")
        self.log_path = self.sb.path("gh-log.jsonl")
        self.db = self.sb.path("coord.db")
        open(self.log_path, "w").close()
        self.sb.env.update({"FAKE_GH_STATE": self.state_path, "FAKE_GH_LOG": self.log_path})
        self.issues([
            {"number": 12, "title": "Checkout epic", "state": "OPEN", "labels": ["epic"],
             "body": "Build checkout.\n\nDepends on #7 and #8.\n\n## Tasks\n- [ ] API\n- [x] Schema\n\n## Notes\nnone"},
            {"number": 7, "title": "Cart", "state": "CLOSED", "labels": [], "body": ""},
            {"number": 8, "title": "Pricing", "state": "OPEN", "labels": [], "body": ""},
        ])

    def tearDown(self):
        self.sb.close()

    def issues(self, rows):
        self.sb.write(self.state_path, {"repo": REPO, "issues": rows})

    def load_state(self):
        with open(self.state_path) as fh:
            return json.load(fh)

    def issue(self, n):
        return next(i for i in self.load_state()["issues"] if i["number"] == n)

    def calls(self):
        with open(self.log_path) as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def writes(self):
        return [c for c in self.calls() if c[:2] in (["issue", "edit"], ["issue", "comment"])]

    def gc(self, *args):
        return self.sb.run("github_coordination.py", *args, "--db", self.db)


class TestWriteGate(GhCase):
    def test_no_flag_writes_nothing_and_exits_3(self):
        r = self.gc("claim", "12", "--repo", REPO, "--actor", "alice")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.writes(), [])
        self.assertIn("Confirmation required", r.stdout)
        self.assertIn("comment on #12", r.stdout)
        self.assertIn("Nothing was written", r.stderr)
        self.assertIn("--yes --plan-id", r.stderr)
        self.assertFalse(os.path.exists(self.db), "cache must not be written before GitHub writes")
        self.assertNotIn(MARK, self.issue(12)["body"])

    def test_yes_applies_edit_comment_and_cache(self):
        r = self.gc("claim", "12", "--repo", REPO, "--actor", "alice", "--branch", "epic/checkout", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        kinds = [c[1] for c in self.writes()]
        self.assertEqual(kinds, ["edit", "comment"])
        issue = self.issue(12)
        state = gc.extract_coordination_state(issue["body"])
        self.assertEqual(state["status"], "claimed")
        self.assertEqual(state["owner"], "alice")
        self.assertEqual(state["branch"], "epic/checkout")
        self.assertEqual(state["review"], "requested")
        self.assertEqual(state["dependencies"], [7, 8])
        self.assertEqual(state["tasks"], [{"title": "API", "done": False}, {"title": "Schema", "done": True}])
        self.assertIn("coordination:claimed", issue["labels"])
        self.assertIn("coordination:review-requested", issue["labels"])
        self.assertTrue(issue["body"].startswith("Build checkout."), "original body text must survive")
        self.assertIn("Neva coordination claimed", issue["comments"][0])
        con = sqlite3.connect(self.db)
        row = con.execute("select id, status, owner from work_items").fetchone()
        con.close()
        self.assertEqual(row, ("github-octo-widgets-epic-12", "in-progress", "alice"))

    def test_plan_id_is_stable_and_guards_apply(self):
        first = self.gc("claim", "12", "--repo", REPO, "--actor", "alice", "--json")
        self.assertEqual(first.returncode, 3)
        pid = json.loads(first.stdout)["writes"]["planId"]
        again = self.gc("claim", "12", "--repo", REPO, "--actor", "alice", "--json")
        self.assertEqual(json.loads(again.stdout)["writes"]["planId"], pid, "timestamps must not change the plan id")
        stale = self.gc("claim", "12", "--repo", REPO, "--actor", "bob", "--yes", "--plan-id", pid)
        self.assertEqual(stale.returncode, 4, stale.stderr)
        self.assertIn("Plan changed", stale.stderr)
        self.assertEqual(self.writes(), [])
        ok = self.gc("claim", "12", "--repo", REPO, "--actor", "alice", "--yes", "--plan-id", pid)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(len(self.writes()), 2)

    def test_dry_run_never_writes(self):
        r = self.gc("claim", "12", "--repo", REPO, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Dry run", r.stdout)
        self.assertEqual(self.writes(), [])

    def test_plan_id_without_yes_is_rejected(self):
        r = self.gc("claim", "12", "--repo", REPO, "--plan-id", "abc")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--plan-id only applies with --yes", r.stderr)

    def test_interactive_yes_and_no(self):
        try:
            import pty  # noqa: F401
        except ImportError:
            self.skipTest("pty not available")
        import pty as _pty
        import select
        import subprocess

        def run_tty(answer):
            master, slave = _pty.openpty()
            p = subprocess.Popen([support.PY, os.path.join(support.SCRIPTS, "github_coordination.py"), "claim", "12",
                                  "--repo", REPO, "--db", self.db], stdin=slave, stdout=subprocess.PIPE,
                                 stderr=slave, env=self.sb.env, cwd=self.sb.work)
            os.close(slave)
            buf = b""
            while b"Type yes" not in buf:
                r, _, _ = select.select([master], [], [], 20)
                if not r:
                    break
                buf += os.read(master, 4096)
            os.write(master, (answer + "\n").encode())
            out, _ = p.communicate(timeout=30)
            os.close(master)
            return p.returncode, buf.decode(errors="replace"), out.decode()

        code, prompt, _ = run_tty("no")
        self.assertIn("Type yes to apply", prompt)
        self.assertEqual(code, 3)
        self.assertEqual(self.writes(), [])
        code, _, out = run_tty("yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.writes()), 2)


class TestActions(GhCase):
    def test_claim_refuses_closed_and_already_claimed(self):
        r = self.gc("claim", "7", "--repo", REPO, "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("#7 is not open", r.stderr)
        self.gc("claim", "12", "--repo", REPO, "--actor", "alice", "--yes")
        r = self.gc("claim", "12", "--repo", REPO, "--actor", "bob", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already claimed by alice", r.stderr)

    def test_validate_fails_on_open_dependency_then_passes(self):
        r = self.gc("validate", "12", "--repo", REPO, "--yes", "--json")
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertEqual(out["missingDependencies"], [8])
        self.assertEqual(gc.extract_coordination_state(self.issue(12)["body"])["validation"], "failed")
        rows = self.load_state()
        rows["issues"][2]["state"] = "CLOSED"
        self.sb.write(self.state_path, rows)
        r = self.gc("validate", "12", "--repo", REPO, "--yes", "--json")
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertIn("coordination:validated", self.issue(12)["labels"])

    def test_publish_requires_validation_and_review(self):
        r = self.gc("publish", "12", "--repo", REPO, "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not ready to publish", r.stderr)
        self.assertIn("#8", r.stderr)
        rows = self.load_state()
        rows["issues"][2]["state"] = "CLOSED"
        self.sb.write(self.state_path, rows)
        r = self.gc("publish", "12", "--repo", REPO, "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("review approval required", r.stderr)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.gc("review", "12", "--repo", REPO, "--review", "approved", "--yes").returncode, 0)
        r = self.gc("publish", "12", "--repo", REPO, "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        issue = self.issue(12)
        self.assertEqual(gc.extract_coordination_state(issue["body"])["status"], "published")
        self.assertIn("coordination:published", issue["labels"])
        self.assertIn("Neva coordination published", issue["comments"][-1])

    def test_review_rejects_unknown_state(self):
        r = self.gc("review", "12", "--repo", REPO, "--review", "lgtm", "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--review: 'lgtm' is not valid", r.stderr)

    def test_unblock_moves_blocked_epic_with_closed_deps(self):
        body = "Blocked on #7\n\n" + block({"status": "blocked", "dependencies": [7], "validation": "failed"})
        self.issues([
            {"number": 20, "title": "Blocked epic", "state": "OPEN", "labels": ["epic", "coordination:blocked"], "body": body},
            {"number": 21, "title": "Still blocked", "state": "OPEN", "labels": ["epic"],
             "body": block({"status": "blocked", "dependencies": [22]})},
            {"number": 22, "title": "Open dep", "state": "OPEN", "labels": [], "body": ""},
            {"number": 7, "title": "Done", "state": "CLOSED", "labels": [], "body": ""},
        ])
        r = self.gc("unblock", "--repo", REPO, "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual([i["issueNumber"] for i in out["items"]], [20])
        state = gc.extract_coordination_state(self.issue(20)["body"])
        self.assertEqual((state["status"], state["validation"]), ("ready", "pending"))
        self.assertNotIn("coordination:blocked", self.issue(20)["labels"])
        self.assertIn("coordination:ready", self.issue(20)["labels"])

    def test_decompose_records_tasks(self):
        r = self.gc("decompose", "12", "--repo", REPO, "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(len(out["tasks"]), 2)
        self.assertEqual(out["dependencyCount"], 2)
        self.assertEqual(out["status"], "claimed")
        self.assertIn("taskCount: 2", self.issue(12)["comments"][0])

    def test_sync_reconciles_labels_and_is_quiet_when_clean(self):
        r = self.gc("sync", "--repo", REPO, "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["count"], 1)
        self.assertIn("coordination:available", self.issue(12)["labels"])
        self.assertIn(MARK, self.issue(12)["body"])
        before = len(self.writes())
        r = self.gc("sync", "--repo", REPO, "--json")
        self.assertEqual(r.returncode, 0, "a clean sync has nothing to confirm")
        self.assertEqual(json.loads(r.stdout)["writes"]["planned"], [])
        self.assertEqual(len(self.writes()), before)

    def test_partial_failure_names_progress(self):
        env = {"FAKE_GH_FAIL_ON": "comment"}
        r = self.sb.run("github_coordination.py", "claim", "12", "--repo", REPO, "--yes", "--db", self.db, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Applied 1 of 2 writes", r.stderr)
        self.assertFalse(os.path.exists(self.db), "cache must not record a half-applied action")

    def test_input_errors_name_the_field(self):
        r = self.gc("claim", "12", "--repo", "widgets")
        self.assertIn("--repo: invalid format", r.stderr)
        r = self.gc("claim", "--repo", REPO)
        self.assertIn("claim: missing issue number", r.stderr)
        r = self.gc("claim", "abc", "--repo", REPO)
        self.assertIn("'abc' is not a positive integer", r.stderr)
        r = self.gc("sync")
        self.assertIn("--repo: missing", r.stderr)

    def test_missing_gh_is_explained(self):
        r = self.sb.run("github_coordination.py", "sync", "--repo", REPO, env={"PATH": "/nonexistent"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("gh CLI not found on PATH", r.stderr)

    def test_policy_overrides_labels_and_marker(self):
        cfg = self.sb.write("work/config/github-native-coordination.json",
                            {"sectionMarker": "team-coord", "labels": {"epic": "initiative"}, "review": {"required": False}})
        self.assertTrue(os.path.exists(cfg))
        rows = self.load_state()
        rows["issues"][0]["labels"] = ["initiative"]
        self.sb.write(self.state_path, rows)
        r = self.gc("claim", "12", "--repo", REPO, "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = self.issue(12)["body"]
        self.assertIn("team-coord:start", body)
        self.assertEqual(gc.extract_coordination_state(body, gc.load_policy(self.sb.work))["review"], "not-requested")


class TestParsing(unittest.TestCase):
    def test_references_and_tasks(self):
        self.assertEqual(gc.extract_issue_references("see #3, #10 and a1#4 x#5 #3"), [3, 5, 10])
        body = "## Tasks\n- [ ] one\n- [X] two\n## Other\n- [ ] not a task"
        self.assertEqual(gc.extract_tasks(body), [{"title": "one", "done": False}, {"title": "two", "done": True}])

    def test_merge_replaces_block_once_and_is_idempotent(self):
        issue = {"number": 1, "body": "Intro\n\n" + block({"status": "claimed"}) + "\n\nOutro"}
        state = gc.get_coordination_state(issue)
        state["status"] = "ready"
        merged = gc.merge_issue_body(issue, state)
        self.assertEqual(merged.count(f"{MARK}:start"), 1)
        self.assertTrue(merged.startswith("Intro"))
        self.assertIn("Outro", merged)
        again = gc.merge_issue_body({"number": 1, "body": merged}, gc.get_coordination_state({"number": 1, "body": merged}))
        self.assertEqual(gc.normalize_body_for_plan(again), gc.normalize_body_for_plan(merged))

    def test_dollar_signs_survive_merge(self):
        issue = {"number": 1, "body": block({"status": "claimed"})}
        state = gc.get_coordination_state(issue)
        state["notes"] = "cost $1 and \\1 and $&"
        self.assertIn("cost $1 and", gc.merge_issue_body(issue, state))

    def test_malformed_block_falls_back_to_defaults(self):
        issue = {"number": 5, "body": f"<!-- {MARK}:start -->\n```json\n{{bad\n```\n<!-- {MARK}:end -->", "labels": []}
        self.assertEqual(gc.get_coordination_state(issue)["status"], "available")

    def test_desired_labels(self):
        labels = gc.desired_labels_for_state({"status": "claimed", "validation": "passed", "review": "approved"})
        self.assertEqual(labels, ["coordination:claimed", "coordination:review-approved", "coordination:synced",
                                  "coordination:validated", "epic"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
