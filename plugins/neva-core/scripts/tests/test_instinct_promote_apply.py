#!/usr/bin/env python3
"""`promote <id> --apply` applies the block wherever it is open, not only in today's file.

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

    def test_apply_finds_the_block_in_an_earlier_file(self):
        r = self.sb.run("promote", "lock-before-write", "--apply", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Applied 1", r.stdout)
        self.assertTrue(os.path.exists(self.promoted))

    def test_apply_finds_it_when_todays_file_also_exists(self):
        self.sb.add("repoA", "other-lesson", 0.9, trigger="when naming a database migration")
        self.sb.run("promote", "other-lesson")
        self.assertTrue(os.path.exists(self.sb.proposal_path()))
        r = self.sb.run("promote", "lock-before-write", "--apply", check=False)
        self.assertIn("Applied 1", r.stdout, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(self.promoted))


if __name__ == "__main__":
    unittest.main()
