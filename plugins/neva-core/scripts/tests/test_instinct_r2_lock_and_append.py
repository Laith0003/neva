#!/usr/bin/env python3
"""One lock covers every read-modify-write of the ledger and the proposal files; an append that finds
its text already there says so and is not counted as applied.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import fcntl
import json
import os
import subprocess
import sys
import unittest

from test_instinct_learning import CLI, PY, InstinctSandbox


class LockCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.state = os.path.join(self.sb.tmp, "state", "neva", "instincts")

    def test_a_held_lock_makes_a_run_wait_then_fail_clearly(self):
        self.sb.add("repoA", "lock-before-write", 0.9)
        self.sb.add("repoB", "lock-before-write", 0.9)
        self.sb.run("propose")
        fh = open(os.path.join(self.state, "promotions.lock"), "a+")
        self.addCleanup(fh.close)
        fcntl.flock(fh, fcntl.LOCK_EX)
        r = self.sb.run("apply-promotions", check=False, env={"NEVA_INSTINCT_LOCK_TIMEOUT": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("promotions.lock", r.stderr)
        self.assertIn("Fix:", r.stderr)

    def test_concurrent_runs_lose_no_decision(self):
        ids = [f"habit-{n}" for n in range(6)]
        for n, iid in enumerate(ids):
            for repo in ("repoA", "repoB"):
                self.sb.run("add", "--id", iid, "--trigger", f"when handling case number {n} of the batch {iid}",
                            "--action", f"Apply the {iid} practice {n} in every change of its kind.",
                            "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose", "--limit", "0")
        env = dict(self.sb.env)
        procs = [subprocess.Popen([PY, CLI, "reject", f"promote-global:{iid}", "--reason", "not wanted"],
                                  cwd=self.sb.repos["repoA"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for iid in ids]
        procs.append(subprocess.Popen([PY, CLI, "propose"], cwd=self.sb.repos["repoA"], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for p in procs:
            p.communicate(timeout=120)
        ledger = json.load(open(os.path.join(self.state, "promotions.json")))
        self.assertEqual(sorted(i for i in ids if ledger[f"promote-global:{i}"]["status"] == "rejected"), ids)
        text = open(self.sb.proposal_path(), encoding="utf-8").read()
        for iid in ids:
            self.assertIn(f"block_id: promote-global:{iid}", text, "a block was lost from the proposal file")


class AlreadyPresentCase(unittest.TestCase):
    def test_an_append_already_in_the_file_is_reported_not_counted(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        sb.run("add", "--id", "explicit-errors", "--trigger", "when handling errors in services", "--action",
               "Return a typed error naming the field.", "--domain", "code-style", "--confidence", "0.95",
               "--scope", "global")
        sb.run("propose")
        text = open(sb.proposal_path(), encoding="utf-8").read()
        fence = text.split("~~~~markdown\n", 1)[1].split("~~~~\n", 1)[0]
        rules = os.path.join(sb.home, ".claude", "rules", "instincts-code-style.md")
        os.makedirs(os.path.dirname(rules))
        open(rules, "w", encoding="utf-8").write(fence)
        sb.tick(sb.proposal_path(), "rule:explicit-errors", "approve")
        r = sb.run("apply-promotions")
        self.assertIn("Applied 0", r.stdout)
        self.assertIn("already present, nothing written", r.stdout + open(sb.proposal_path(), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
