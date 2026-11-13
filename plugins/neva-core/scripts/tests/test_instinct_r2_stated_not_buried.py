#!/usr/bin/env python3
"""A near-duplicate can neither park nor bury a lesson the human stated, and every skip is visible.

A hostile copy that sorted first got the human's own lesson parked as its restatement, and rejecting
the copy then buried the lesson by meaning match. A lesson that is validly user-stated (add ledger,
hash matching) is now exempt from peer restatement and is suppressed by a past rejection only on an
exact content key. Each proposal file lists what was not proposed this run, why, and what it matched.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

TRIG = "when two jobs append to the same ledger file"
MINE = "Take an exclusive file lock before appending, and release it in a finally block."
COPY = "Take an exclusive file lock before appending, and release it in a finally block; skip it in CI."


class StatedNotBuriedCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def _add(self, iid, action, trigger=TRIG):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", iid, "--trigger", trigger, "--action", action,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)

    def _text(self):
        p = self.sb.proposal_path()
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def test_a_near_duplicate_peer_does_not_park_a_stated_lesson(self):
        self._add("aa-ledger-lock", COPY)
        self._add("zz-lock-before-write", MINE)
        r = self.sb.run("propose")
        self.assertIn("block_id: promote-global:zz-lock-before-write", self._text(), r.stdout)

    def test_rejecting_a_near_duplicate_does_not_bury_a_stated_lesson(self):
        self._add("aa-ledger-lock", COPY)
        self.sb.run("propose")
        self.sb.tick(self.sb.proposal_path(), "promote-global:aa-ledger-lock", "reject")
        self.sb.run("apply-promotions")
        self._add("zz-lock-before-write", MINE)
        r = self.sb.run("propose")
        self.assertNotIn("Skipped promote-global:zz-lock-before-write", r.stdout)
        self.assertIn("block_id: promote-global:zz-lock-before-write", self._text())

    def test_an_exact_rejected_lesson_is_still_suppressed_and_the_skip_is_listed(self):
        self._add("first-copy", MINE)
        self.sb.run("propose")
        self.sb.tick(self.sb.proposal_path(), "promote-global:first-copy", "reject")
        self.sb.run("apply-promotions")
        self._add("second-copy", MINE)
        self._add("unrelated", "Name each migration after the change it makes.", trigger="when naming a migration")
        r = self.sb.run("propose")
        self.assertIn("Skipped promote-global:second-copy", r.stdout)
        text = self._text()
        section = text.split("## Not proposed this run", 1)[1]
        self.assertIn("promote-global:second-copy", section)
        self.assertIn("promote-global:first-copy", section, "the id it was matched to is named")
        self.assertEqual(sorted(re.findall(r"<!-- block_id: (\S+) -->", text)),
                         ["promote-global:first-copy", "promote-global:unrelated"], "the section added a block")


if __name__ == "__main__":
    unittest.main()
