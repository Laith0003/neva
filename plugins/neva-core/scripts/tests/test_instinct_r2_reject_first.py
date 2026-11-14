#!/usr/bin/env python3
"""A reject tick always succeeds, and it is read before anything that could throw it away.

A legacy block ticked reject was withdrawn before the tick was read, and the lesson came back; a rule
block whose text fails the checks, ticked reject, was refused with advice to tick reject. A rejection
writes nothing, so it needs no hash and no text check: only the engine's own record of the block.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import unittest

from test_instinct_learning import InstinctSandbox


class RejectFirstCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.ledger_path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")

    def _ledger(self):
        return json.load(open(self.ledger_path, encoding="utf-8"))

    def test_a_legacy_block_ticked_reject_is_rejected_not_withdrawn(self):
        self.sb.add("repoA", "lock-before-write", 0.9)
        self.sb.add("repoB", "lock-before-write", 0.9)
        self.sb.run("propose")
        bid = "promote-global:lock-before-write"
        ledger = self._ledger()
        for key in ("rendered_sha256", "ticked_at_propose", "destination", "sources"):
            ledger[bid].pop(key, None)
        json.dump(ledger, open(self.ledger_path, "w"))
        self.sb.tick(self.sb.proposal_path(), bid, "reject")
        r = self.sb.run("apply-promotions")
        self.assertIn("rejected 1", r.stdout)
        self.assertEqual(self._ledger()[bid]["status"], "rejected")
        r = self.sb.run("propose")
        self.assertNotIn("Proposed", r.stdout, "a rejected lesson came back")

    def test_a_reject_tick_on_a_rule_block_with_failing_text_succeeds(self):
        self.sb.run("add", "--id", "explicit-errors", "--trigger", "when handling errors in services",
                    "--action", "Return a typed error naming the field.", "--domain", "code-style",
                    "--confidence", "0.95", "--scope", "global")
        self.sb.run("propose")
        path = self.sb.proposal_path()
        text = open(path, encoding="utf-8").read().replace(
            "Return a typed error naming the field.\n", "Return a typed error naming the field.\n- item\n", 1)
        open(path, "w", encoding="utf-8").write(text)
        self.sb.tick(path, "rule:explicit-errors", "reject")
        r = self.sb.run("apply-promotions", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("rejected 1", r.stdout)
        self.assertEqual(self._ledger()["rule:explicit-errors"]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
