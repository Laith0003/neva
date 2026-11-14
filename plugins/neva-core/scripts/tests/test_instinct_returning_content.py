#!/usr/bin/env python3
"""A withdrawn block comes back without the gate only while it still says what it said when withdrawn.

A legacy block is withdrawn once and promised back for a fresh tick. The promise covers the lesson that
was withdrawn, not the id: when the notes behind the id are rewritten afterwards, the block is a new
candidate and goes through the same checks as any other (a matching earlier decision, the quality gate).

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import glob
import json
import os
import unittest

import test_instinct_ledger_authority as la

BID = la.BID
OTHER = "promote-global:pin-tool-versions"
OTHER_TRIGGER = "when a build script installs a command line tool"
OTHER_ACTION = "Pin the exact version of every tool the build installs, and record it in the lockfile."
OLD_TRIGGER = "when two jobs append to the same ledger file"


class ReturningContentCase(la.LedgerAuthorityCase):
    test_a_destination_row_changed_to_a_rules_file_is_ignored = None
    test_a_kind_row_that_disagrees_with_the_id_is_refused = None
    test_a_non_rule_id_writing_into_a_rules_file_gets_the_rule_checks = None

    def _withdraw_and_reject_other(self, drop_key=False):
        """BID is made legacy and withdrawn; a second lesson is proposed and rejected by the human.
        drop_key: the entry is as old ledgers hold it, with no content key from propose."""
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "pin-tool-versions", "--trigger", OTHER_TRIGGER, "--action", OTHER_ACTION,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose")
        ledger = self._ledger()
        legacy_keys = ("rendered_sha256", "ticked_at_propose", "destination", "sources")
        for key in legacy_keys + (("content_key", "content_tokens") if drop_key else ()):
            ledger[BID].pop(key, None)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self.sb.tick(self.sb.proposal_path(), OTHER, "reject")
        self.sb.run("apply-promotions", check=False)
        ledger = self._ledger()
        self.assertEqual(ledger[BID]["status"], "withdrawn", ledger[BID])
        self.assertEqual(ledger[OTHER]["status"], "rejected", ledger[OTHER])

    def _rewrite_notes(self):
        """The notes behind BID now say what the rejected lesson said, written on disk as the analyzer
        would, not through `add`."""
        notes = glob.glob(os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "*", "lock-before-write.md"))
        self.assertEqual(len(notes), 2, notes)
        for note in notes:
            with open(note, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn(la.ACTION, text)
            self.assertIn(OLD_TRIGGER, text)
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(text.replace(la.ACTION, OTHER_ACTION).replace(OLD_TRIGGER, OTHER_TRIGGER))

    def test_a_withdrawn_id_whose_notes_changed_meets_the_earlier_rejection(self):
        self._withdraw_and_reject_other()
        self._rewrite_notes()
        r = self.sb.run("propose", check=False)
        entry = self._ledger()[BID]
        self.assertNotEqual(entry["status"], "proposed",
                            "a withdrawn id with rewritten notes was filed past a rejection of the same content\n"
                            + r.stdout + r.stderr)
        self.assertIn(f"Skipped {BID}: says the same as {OTHER}", r.stdout, r.stdout + r.stderr)

    def test_an_unchanged_withdrawn_block_still_comes_back(self):
        self._withdraw_and_reject_other()
        r = self.sb.run("propose")
        entry = self._ledger()[BID]
        self.assertEqual(entry["status"], "proposed", r.stdout + r.stderr)
        self.assertIn("rendered_sha256", entry)

    def test_an_old_entry_with_no_key_is_keyed_at_withdrawal(self):
        self._withdraw_and_reject_other(drop_key=True)
        self.assertTrue(self._ledger()[BID].get("withdrawn_content_key"), self._ledger()[BID])
        self._rewrite_notes()
        r = self.sb.run("propose", check=False)
        self.assertNotEqual(self._ledger()[BID]["status"], "proposed", r.stdout + r.stderr)

    def test_an_old_entry_with_no_key_still_comes_back_unchanged(self):
        self._withdraw_and_reject_other(drop_key=True)
        r = self.sb.run("propose")
        self.assertEqual(self._ledger()[BID]["status"], "proposed", r.stdout + r.stderr)

    def test_a_withdrawn_entry_with_no_recorded_content_goes_through_the_checks(self):
        # A ledger withdrawn by an engine that recorded no key: nothing vouches for the content.
        self._withdraw_and_reject_other()
        ledger = self._ledger()
        ledger[BID].pop("withdrawn_content_key", None)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self._rewrite_notes()
        r = self.sb.run("propose", check=False)
        self.assertNotEqual(self._ledger()[BID]["status"], "proposed", r.stdout + r.stderr)

    def test_the_withdrawal_records_the_content_it_withdrew(self):
        self._withdraw_and_reject_other()
        self.assertTrue(self._ledger()[BID].get("withdrawn_content_key"), self._ledger()[BID])


if __name__ == "__main__":
    unittest.main()
