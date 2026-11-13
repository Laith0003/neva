#!/usr/bin/env python3
"""A legacy block (proposed before the rendered hash existed) is never applied on partial evidence.

Every one is withdrawn, said once on stderr and once in the promotion event log, and filed again by the
next propose with its hash recorded, so it needs a fresh tick. A second run says nothing new.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest

import test_instinct_ledger_authority as la

BID = la.BID


class LegacyWithdrawalCase(la.LedgerAuthorityCase):
    def _make_legacy(self):
        ledger = self._ledger()
        for key in ("rendered_sha256", "ticked_at_propose", "destination", "sources"):
            ledger[BID].pop(key, None)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)

    test_a_destination_row_changed_to_a_rules_file_is_ignored = None
    test_a_kind_row_that_disagrees_with_the_id_is_refused = None
    test_a_non_rule_id_writing_into_a_rules_file_gets_the_rule_checks = None

    def test_a_ticked_legacy_block_is_withdrawn_once_and_filed_again_with_a_hash(self):
        self._make_legacy()
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertFalse(os.path.exists(self.promoted), "a legacy block was applied")
        self.assertEqual(r.stderr.count(f"block {BID}"), 1, r.stderr)
        self.assertIn("needs a fresh tick", r.stderr)
        events = open(self.sb.events_path(), encoding="utf-8").read()
        self.assertEqual(events.count('"withdrawn"'), 1)
        self.sb.run("propose")
        self.assertIn("rendered_sha256", self._ledger()[BID])
        # A second night: nothing is withdrawn or said again.
        r2 = self.sb.run("apply-promotions", check=False)
        self.assertNotIn("withdrawn", r2.stderr)
        self.sb.run("propose")
        events = open(self.sb.events_path(), encoding="utf-8").read()
        self.assertEqual(events.count('"withdrawn"'), 1)
        self.assertEqual(len(re.findall(rf"<!-- block_id: {re.escape(BID)} -->", self._text())), 1)

    def test_an_unticked_legacy_block_is_withdrawn_too(self):
        self._make_legacy()
        r = self.sb.run("apply-promotions", check=False)
        self.assertIn("needs a fresh tick", r.stderr)

    def test_the_re_proposed_block_applies_after_a_tick(self):
        self._make_legacy()
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        self.sb.run("apply-promotions", check=False)
        self.sb.run("propose")
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self.sb.run("apply-promotions")
        self.assertIn("Applied 1", r.stdout)
        self.assertTrue(os.path.exists(self.promoted))



if __name__ == "__main__":
    unittest.main()
