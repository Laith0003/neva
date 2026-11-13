#!/usr/bin/env python3
"""Restatement is not decided by the size of the other text.

The overlap coefficient divides shared stems by the smaller set, so a short lesson scored 1.0 against
any long paragraph sharing three stems, and one broad candidate made every later candidate in the
same run fail as its restatement. Candidates are now compared with each other by Jaccard, and a
short lesson is compared with the written corpus by Jaccard too; the thresholds keep their defaults
and can be set in the identity file.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import re
import sys
import unittest

from test_instinct_learning import LEARNING_SCRIPTS, InstinctSandbox

sys.path.insert(0, LEARNING_SCRIPTS)
import quality_gate  # noqa: E402

BROAD = ("Before appending to a shared ledger file take an exclusive lock, write the record, flush it, "
         "fsync the file, release the lock in a finally block, rotate the file at midnight, compress "
         "yesterday's file, verify the checksum, alert the owner on mismatch, and keep thirty days.")
NARROW = "Release the exclusive lock in a finally block after the record is written."


class CandidateStarvationCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def _lesson(self, iid, action, trigger):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", iid, "--trigger", trigger, "--action", action,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)

    def test_a_broad_candidate_does_not_park_a_narrow_one(self):
        self._lesson("aaa-ledger-hygiene", BROAD, "when maintaining the shared ledger file")
        self._lesson("bbb-release-lock", NARROW, "when holding a file lock in a job")
        r = self.sb.run("propose")
        with open(self.sb.proposal_path(), encoding="utf-8") as fh:
            ids = re.findall(r"<!-- block_id: (\S+) -->", fh.read())
        self.assertIn("promote-global:aaa-ledger-hygiene", ids, r.stdout)
        self.assertIn("promote-global:bbb-release-lock", ids, r.stdout)


class ShortLessonCase(unittest.TestCase):
    def test_a_short_lesson_is_not_a_restatement_of_a_long_paragraph(self):
        lesson = set(quality_gate.instinct_match.tokens("Rotate staging secrets weekly"))
        paragraph = set(quality_gate.instinct_match.tokens(
            "Staging deploys run nightly; secrets live in the vault, rotate them when a teammate leaves, "
            "and keep the weekly report of every credential, owner, expiry and scope in the team folder."))
        self.assertGreaterEqual(len(lesson & paragraph), 3)
        self.assertIsNone(quality_gate.restates(lesson, [("rule ops.md", paragraph)]))

    def test_a_long_lesson_restating_a_paragraph_is_still_caught(self):
        text = "Return a typed error that names the field and how to fix it, every time an error reaches a user."
        stems = set(quality_gate.instinct_match.tokens(text))
        unit = set(quality_gate.instinct_match.tokens(
            "Errors name the field and the fix: return a typed error that names the field and how to fix it."))
        self.assertIsNotNone(quality_gate.restates(stems, [("rule house.md", unit)]))


class ThresholdConfigCase(unittest.TestCase):
    def test_defaults_hold_and_the_identity_file_can_set_them(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        path = os.path.join(sb.tmp, "identity.env")
        self.assertEqual(quality_gate.load_thresholds(path),
                         {"overlap": quality_gate.OVERLAP_THRESHOLD, "min_shared": quality_gate.MIN_SHARED})
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('NEVA_GATE_OVERLAP_THRESHOLD="0.8"\nNEVA_GATE_MIN_SHARED="4"\n')
        self.assertEqual(quality_gate.load_thresholds(path), {"overlap": 0.8, "min_shared": 4})
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('NEVA_GATE_OVERLAP_THRESHOLD="lots"\n')
        with self.assertRaises(ValueError) as ctx:
            quality_gate.load_thresholds(path)
        self.assertIn("NEVA_GATE_OVERLAP_THRESHOLD", str(ctx.exception))
        self.assertIn("Fix:", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
