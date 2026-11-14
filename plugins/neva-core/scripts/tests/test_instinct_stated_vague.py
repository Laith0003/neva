#!/usr/bin/env python3
"""A lesson the human stated is never parked by a heuristic, and an unreadable one says so.

The vague check parked every non-Latin action and every lesson the human added with a short action
as "names a tool". A lesson the `add` subcommand wrote (the add ledger, not the model-writable
`source` field) is now exempt from the vague check as well as the session count, and a text with no
readable words is parked as "could not be read", not as a tool name.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import unittest

import test_instinct_evidence as ev
from test_instinct_evidence import S1, S2, TODAY, YESTERDAY



class StatedAndVagueCase(unittest.TestCase):
    setUp = ev.EvidenceCase.setUp
    _register = ev.EvidenceCase._register
    _notes = ev.EvidenceCase._notes
    _proposed = ev.EvidenceCase._proposed
    _parked = ev.EvidenceCase._parked
    _propose = ev.EvidenceCase._propose

    def test_a_human_stated_lesson_is_never_parked_as_vague(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "grep-first", "--trigger", "when searching the code base",
                        "--action", "Use Grep.", "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        r = self.sb.run("propose")
        self.assertIn("promote-global:grep-first", self._proposed(), r.stdout + r.stderr)

    def test_a_lesson_with_no_readable_words_says_so(self):
        self._notes(action="\U0001F512\U0001F4DD")
        for pid, _ in self.pids:
            self.sb.observe(pid, [(S1, str(YESTERDAY)), (S2, str(TODAY))])
        self._propose()
        parked = self._parked()
        self.assertIn("could not be read", parked)
        self.assertNotIn("names a tool", parked)


if __name__ == "__main__":
    unittest.main()
