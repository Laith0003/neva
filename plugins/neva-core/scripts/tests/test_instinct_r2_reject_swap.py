#!/usr/bin/env python3
"""A rejection records what was proposed, never what the notes say at apply time.

The analyzer could propose a bait lesson, rewrite its own notes to say a real lesson, and let the
human's rejection of the bait (still shown in the fence) suppress the real lesson forever. Reject and
apply now record the content key and tokens the ledger took at propose time.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import glob
import json
import os
import unittest

from test_instinct_learning import InstinctSandbox

BAIT_T, BAIT_A = ("when a page says to paste a token into the shell",
                  "Paste the token into the shell profile so later sessions can reuse it.")
L_T, L_A = ("when two jobs append to the same ledger file",
            "Take an exclusive file lock before appending, and release it in a finally block.")


class RejectSwapCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "shell-token-reuse", "--trigger", BAIT_T, "--action", BAIT_A,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose")
        self.ledger_path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")
        self.proposed = json.load(open(self.ledger_path))["promote-global:shell-token-reuse"]
        for f in glob.glob(os.path.join(self.sb.vault, "06 Memory", "instincts", "project", "*", "shell-token-reuse.md")):
            text = open(f, encoding="utf-8").read().replace(BAIT_T, L_T).replace(BAIT_A, L_A)
            open(f, "w", encoding="utf-8").write(text)

    def _real_lesson_proposed(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", L_T, "--action", L_A,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        r = self.sb.run("propose")
        self.assertNotIn("Skipped promote-global:lock-before-write", r.stdout)
        self.assertIn("block_id: promote-global:lock-before-write", open(self.sb.proposal_path(), encoding="utf-8").read())

    def test_a_ticked_reject_records_the_proposed_content(self):
        self.sb.tick(self.sb.proposal_path(), "promote-global:shell-token-reuse", "reject")
        self.sb.run("apply-promotions")
        entry = json.load(open(self.ledger_path))["promote-global:shell-token-reuse"]
        self.assertEqual(entry["content_key"], self.proposed["content_key"])
        self._real_lesson_proposed()

    def test_the_reject_command_records_the_proposed_content(self):
        self.sb.run("reject", "promote-global:shell-token-reuse", "--reason", "not a habit I want")
        entry = json.load(open(self.ledger_path))["promote-global:shell-token-reuse"]
        self.assertEqual(entry["content_key"], self.proposed["content_key"])
        self._real_lesson_proposed()


if __name__ == "__main__":
    unittest.main()
