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
from test_instinct_learning import InstinctSandbox

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

    def test_a_returning_block_still_meets_a_rejection_of_the_same_content(self):
        # He rejected this very lesson under another id while the legacy block was open. The legacy
        # block is withdrawn and comes back unchanged: it skips the gate, never his decision.
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-first-then-append", "--trigger", OLD_TRIGGER, "--action", la.ACTION,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("promote", "lock-first-then-append")
        twin = "promote-global:lock-first-then-append"
        self.assertEqual(self._ledger()[twin]["status"], "proposed", self._ledger().get(twin))
        ledger = self._ledger()
        for key in ("rendered_sha256", "ticked_at_propose", "destination", "sources", "content_key", "content_tokens"):
            ledger[BID].pop(key, None)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self.sb.tick(self.sb.proposal_path(), twin, "reject")
        self.sb.run("apply-promotions", check=False)
        ledger = self._ledger()
        self.assertEqual(ledger[twin]["status"], "rejected", ledger[twin])
        self.assertEqual(ledger[BID]["status"], "withdrawn", ledger[BID])
        r = self.sb.run("propose", check=False)
        self.assertNotEqual(self._ledger()[BID]["status"], "proposed",
                            "a withdrawn block came back past a rejection of the same content\n" + r.stdout + r.stderr)

    def test_notes_rewritten_before_the_withdrawal_do_not_carry_the_promise(self):
        # An old entry holds no key from propose. If its notes no longer say what the block shows when
        # it is withdrawn, nothing vouches for the new text: it is a new candidate.
        ledger = self._ledger()
        for key in ("rendered_sha256", "ticked_at_propose", "destination", "sources", "content_key", "content_tokens"):
            ledger[BID].pop(key, None)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self._rewrite_notes()
        self.sb.run("apply-promotions", check=False)
        entry = self._ledger()[BID]
        self.assertEqual(entry["status"], "withdrawn", entry)
        self.assertFalse(entry.get("withdrawn_content_key"), entry)

    def test_the_withdrawal_records_the_content_it_withdrew(self):
        self._withdraw_and_reject_other()
        self.assertTrue(self._ledger()[BID].get("withdrawn_content_key"), self._ledger()[BID])


RULE_BID = "rule:explicit-errors"
RULE_TRIGGER = "when handling errors in services"
RULE_ACTION = "Return a typed error naming the field and the fix."
LEGACY_KEYS = ("rendered_sha256", "ticked_at_propose", "destination", "sources", "content_key", "content_tokens")


class ReturningRuleBlockCase(unittest.TestCase):
    """A rule block's fence holds the rule text, not the instinct note. The promise made at withdrawal
    covers it too: an unchanged legacy rule block is keyed and comes back without the gate."""

    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.config = os.path.join(self.sb.tmp, "claude-config")
        os.makedirs(self.config)
        self.env = {"CLAUDE_CONFIG_DIR": self.config}
        self.state = os.path.join(self.sb.tmp, "state", "neva", "instincts")
        self.sb.run("add", "--id", "explicit-errors", "--trigger", RULE_TRIGGER, "--action", RULE_ACTION,
                    "--domain", "code-style", "--confidence", "0.95", "--scope", "global", env=self.env)
        self.sb.run("propose", env=self.env)
        ledger = self._ledger()
        self.assertEqual(ledger[RULE_BID]["status"], "proposed", ledger)
        self.key_at_propose = ledger[RULE_BID]["content_key"]
        for key in LEGACY_KEYS:
            ledger[RULE_BID].pop(key, None)
        self._write("promotions.json", ledger)

    def _ledger(self):
        with open(os.path.join(self.state, "promotions.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, name, data):
        with open(os.path.join(self.state, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def _rewrite_note(self):
        notes = glob.glob(os.path.join(self.sb.vault, "06 Memory", "instincts", "**", "explicit-errors.md"),
                          recursive=True)
        self.assertEqual(len(notes), 1, notes)
        with open(notes[0], encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(RULE_ACTION, text)
        with open(notes[0], "w", encoding="utf-8") as fh:
            fh.write(text.replace(RULE_ACTION, OTHER_ACTION).replace(RULE_TRIGGER, OTHER_TRIGGER))

    def test_an_unchanged_legacy_rule_block_is_keyed_at_withdrawal(self):
        self.sb.run("apply-promotions", check=False, env=self.env)
        entry = self._ledger()[RULE_BID]
        self.assertEqual(entry["status"], "withdrawn", entry)
        self.assertEqual(entry.get("withdrawn_content_key"), self.key_at_propose, entry)

    def test_an_unchanged_legacy_rule_block_comes_back_without_the_gate(self):
        self.sb.run("apply-promotions", check=False, env=self.env)
        # Proposed under the old rules: no record that these were his own words, so the gate alone
        # would park it as thin. The promise made at withdrawal is what brings it back.
        self._write("user-stated.json", {})
        r = self.sb.run("propose", check=False, env=self.env)
        self.assertEqual(self._ledger()[RULE_BID]["status"], "proposed", r.stdout + r.stderr)

    def test_a_rule_note_rewritten_before_the_withdrawal_does_not_carry_the_promise(self):
        self._rewrite_note()
        self.sb.run("apply-promotions", check=False, env=self.env)
        entry = self._ledger()[RULE_BID]
        self.assertEqual(entry["status"], "withdrawn", entry)
        self.assertFalse(entry.get("withdrawn_content_key"), entry)


if __name__ == "__main__":
    unittest.main()
