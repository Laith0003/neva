#!/usr/bin/env python3
"""`promote <id> --apply` files the block and stops (issue 27, B2): it names the file the block is
open in, which may be an earlier day's file, and applies nothing until the human ticks it there.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import unittest

from test_instinct_learning import InstinctSandbox

BID = "promote-global:lock-before-write"


class PromoteApplyCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.sb.add("repoA", "lock-before-write", 0.9)
        self.sb.run("promote", "lock-before-write")
        today = self.sb.proposal_path()
        self.older = os.path.join(os.path.dirname(today), "Instinct promotions 2020-01-01.md")
        os.rename(today, self.older)
        ledger_path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")
        with open(ledger_path) as fh:
            ledger = json.load(fh)
        ledger[BID]["file"] = self.older
        with open(ledger_path, "w") as fh:
            json.dump(ledger, fh)
        self.promoted = os.path.join(self.sb.vault, "06 Memory", "instincts", "global", "lock-before-write.md")

    def test_apply_names_the_earlier_file_and_applies_nothing(self):
        r = self.sb.run("promote", "lock-before-write", "--apply", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Instinct promotions 2020-01-01.md", r.stdout)
        self.assertIn("Fix: tick approve", r.stdout)
        self.assertFalse(os.path.exists(self.promoted))

    def test_the_tick_in_the_earlier_file_applies_it(self):
        self.sb.add("repoA", "other-lesson", 0.9, trigger="when naming a database migration")
        self.sb.run("promote", "other-lesson")
        self.assertTrue(os.path.exists(self.sb.proposal_path()))
        self.sb.run("promote", "lock-before-write", "--apply", check=False)
        self.assertFalse(os.path.exists(self.promoted))
        self.sb.tick(self.older, BID, "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertIn("Applied 1", r.stdout, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.promoted))


if __name__ == "__main__":
    unittest.main()
