#!/usr/bin/env python3
"""What apply writes comes from the engine's ledger, and a block the ledger cannot vouch for is filed again.

The rendered hash only proves the box was not written ticked; it does not freeze the table rows, so a
hashed block's Kind, Proposed destination and Write mode rows could be changed after propose, and the
rule-text checks were chosen by the block id. Apply now takes kind, destination and write mode from
the ledger entry, refuses a Kind row that disagrees with the id, and runs the rule-text checks on any
write that lands in a rules/instincts-*.md file. A legacy block (no rendered hash) is never applied:
it is withdrawn once, said once, and filed again with its hash.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

BID = "promote-global:lock-before-write"
ACTION = "Take an exclusive file lock before appending, and release it in a finally block."


class LedgerAuthorityCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.ledger_path = os.path.join(self.sb.tmp, "state", "neva", "instincts", "promotions.json")
        self.rules = os.path.join(self.sb.home, ".claude", "rules", "instincts-code-style.md")
        self.promoted = os.path.join(self.sb.vault, "06 Memory", "instincts", "global", "lock-before-write.md")
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", "when two jobs append to the same ledger file",
                        "--action", ACTION, "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose")

    def _text(self):
        with open(self.sb.proposal_path(), encoding="utf-8") as fh:
            return fh.read()

    def _row(self, name, value, bid=BID):
        text = self._text()
        start = text.index(f"block_id: {bid}")
        m = re.compile(rf"^\| {re.escape(name)} \| .* \|$", re.M).search(text, start)
        with open(self.sb.proposal_path(), "w", encoding="utf-8") as fh:
            fh.write(text[:m.start()] + f"| {name} | {value} |" + text[m.end():])

    def _ledger(self):
        with open(self.ledger_path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_destination_row_changed_to_a_rules_file_is_ignored(self):
        self._row("Proposed destination", "`~/.claude/rules/instincts-code-style.md`")
        self._row("Write mode", "append")
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertFalse(os.path.exists(self.rules), "a row changed after propose redirected the write")
        self.assertTrue(os.path.exists(self.promoted), r.stdout + r.stderr)

    def test_a_kind_row_that_disagrees_with_the_id_is_refused(self):
        self._row("Kind", "rule")
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertFalse(os.path.exists(self.promoted), r.stdout + r.stderr)
        self.assertIn("Kind", r.stderr)
        self.assertIn(BID, r.stderr)

    def test_a_non_rule_id_writing_into_a_rules_file_gets_the_rule_checks(self):
        # The ledger itself is made to point a promote-global block at a rules file, with text the rule
        # builder would refuse: the checks follow the destination, not the id.
        ledger = self._ledger()
        ledger[BID]["destination"] = "`~/.claude/rules/instincts-code-style.md`"
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertFalse(os.path.exists(self.rules), r.stdout + r.stderr)
        self.assertIn("rule", r.stderr)


if __name__ == "__main__":
    unittest.main()
