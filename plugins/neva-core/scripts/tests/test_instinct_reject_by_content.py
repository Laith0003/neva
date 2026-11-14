#!/usr/bin/env python3
"""Rejected stays rejected, keyed by what the block says, not by its slug.

A slug comes from trigger text or a cluster's shared keywords, so the analyzer rewording a trigger
gives the same lesson a new slug and it used to come back. These tests reject a block, reword the
lesson under a new id, and prove it is not proposed again; prove that a genuinely different lesson
still is; and prove the `reject` and `list --rejected` commands record and show the slug, the
content key, the reason and the date.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

FIRST = "when handling errors in services"
REWORDED = "When handling the errors in a service!"


class RejectByContentCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def _pair(self, iid, trigger, action="Return a typed error naming the field and the fix."):
        for repo, conf in (("repoA", 0.9), ("repoB", 0.85)):
            self.sb.run("add", "--id", iid, "--trigger", trigger, "--action", action,
                        "--domain", "code-style", "--confidence", str(conf), cwd=repo)

    def _ids(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

    def _ledger(self):
        with open(os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")) as fh:
            return json.load(fh)

    def _reject_by_tick(self, bid):
        self.sb.tick(self.sb.proposal_path(), bid, "reject")
        self.sb.run("apply-promotions")

    def test_a_reworded_lesson_under_a_new_slug_does_not_return_after_a_ticked_reject(self):
        self._pair("explicit-errors", FIRST)
        self.sb.run("propose")
        self._reject_by_tick("promote-global:explicit-errors")
        self._pair("errors-explicit-in-services", REWORDED)
        r = self.sb.run("propose")
        self.assertNotIn("promote-global:errors-explicit-in-services", self._ids(), r.stdout + r.stderr)

    def test_a_different_lesson_is_still_proposed(self):
        self._pair("explicit-errors", FIRST)
        self.sb.run("propose")
        self._reject_by_tick("promote-global:explicit-errors")
        self._pair("small-commits", "when committing a change set",
                   action="Keep each commit to one concern with its tests.")
        self.sb.run("propose")
        self.assertIn("promote-global:small-commits", self._ids())

    def test_reject_command_records_slug_content_key_reason_and_date(self):
        self._pair("explicit-errors", FIRST)
        self.sb.run("propose")
        r = self.sb.run("reject", "explicit-errors", "--reason", "already a standing rule")
        self.assertIn("promote-global:explicit-errors", r.stdout)
        entry = self._ledger()["promote-global:explicit-errors"]
        self.assertEqual(entry["status"], "rejected")
        self.assertEqual(entry["slug"], "explicit-errors")
        self.assertEqual(entry["reason"], "already a standing rule")
        self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(entry["content_key"], r"^[0-9a-f]{16}$")
        with open(self.sb.proposal_path(), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("- [x] reject", text)
        self.assertIn("already a standing rule", text)
        listing = self.sb.run("list", "--rejected").stdout
        self.assertIn("promote-global:explicit-errors", listing)
        self.assertIn("already a standing rule", listing)
        self.assertIn(entry["content_key"], listing)
        self._pair("errors-explicit-in-services", REWORDED)
        self.sb.run("propose")
        self.assertNotIn("promote-global:errors-explicit-in-services", self._ids())

    def test_reject_names_the_fix_for_an_unknown_id(self):
        r = self.sb.run("reject", "no-such-block", "--reason", "x", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no-such-block", r.stderr)
        self.assertIn("Fix:", r.stderr)

    def test_a_rejection_recorded_before_content_keys_existed_still_holds(self):
        """A ledger entry written by the slug-only engine (no content key) whose block is still in
        its proposal file, ticked reject: the content is recovered from the vault."""
        self._pair("explicit-errors", FIRST)
        self.sb.run("propose")
        self._reject_by_tick("promote-global:explicit-errors")
        ledger_path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")
        ledger = self._ledger()
        entry = ledger["promote-global:explicit-errors"]
        ledger["promote-global:explicit-errors"] = {k: entry[k] for k in ("status", "file", "date")}
        with open(ledger_path, "w") as fh:
            json.dump(ledger, fh)
        self._pair("errors-explicit-in-services", REWORDED)
        self.sb.run("propose")
        self.assertNotIn("promote-global:errors-explicit-in-services", self._ids())


if __name__ == "__main__":
    unittest.main()
