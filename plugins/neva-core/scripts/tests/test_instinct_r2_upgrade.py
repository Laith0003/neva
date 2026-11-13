#!/usr/bin/env python3
"""On the first run after the upgrade nothing he approved or stated is parked for good.

The fixture is the state an install made by the pre-upgrade code has: notes written with
`source: user-stated` and no add ledger, a global note from an applied promotion and no
promoted-notes record, ledger entries with only status, file and date, and an open block with no
rendered hash. From there: a withdrawn block comes back for its fresh tick without the gate; an
applied promotion is backfilled from the engine's own ledger and its rule is proposed; notes that
claim to be his are listed once in one block for him to confirm; and `add --restate` re-vouches a
note he edited.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

ACTION = "Take an exclusive file lock before appending, and release it in a finally block."
TRIG = "when two jobs append to the same ledger file"


class UpgradeCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.state = os.path.join(self.sb.tmp, "state", "neva", "instincts")
        self.ledger_path = os.path.join(self.state, "promotions.json")

    def _downgrade_state(self):
        """Remove what only the new code writes, as an install made before the upgrade has it."""
        for name in ("user-stated.json", "promoted-notes.json", "note-sessions.json", "parked.json"):
            p = os.path.join(self.state, name)
            if os.path.exists(p):
                os.remove(p)
        if not os.path.exists(self.ledger_path):
            return
        ledger = json.load(open(self.ledger_path))
        for bid, entry in ledger.items():
            ledger[bid] = {k: entry[k] for k in ("status", "file", "date") if k in entry}
        json.dump(ledger, open(self.ledger_path, "w"))

    def _ids(self):
        p = self.sb.proposal_path()
        return re.findall(r"<!-- block_id: (\S+) -->", open(p, encoding="utf-8").read()) if os.path.exists(p) else []

    def test_an_approved_promotion_and_its_rule_survive_the_upgrade(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", TRIG, "--action", ACTION,
                        "--domain", "code-style", "--confidence", "0.95", cwd=repo)
        self.sb.run("propose")
        self.sb.tick(self.sb.proposal_path(), "promote-global:lock-before-write", "approve")
        self.sb.run("apply-promotions")
        os.remove(self.sb.proposal_path())  # the rule block is proposed after the upgrade, not before
        ledger = json.load(open(self.ledger_path))
        for bid in [b for b in ledger if b.startswith("rule:")]:
            del ledger[bid]
        json.dump(ledger, open(self.ledger_path, "w"))
        self._downgrade_state()
        r = self.sb.run("propose")
        self.assertIn("rule:lock-before-write", self._ids(), r.stdout + r.stderr)

    def test_a_withdrawn_block_is_re_proposed_without_the_gate(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", TRIG, "--action", ACTION,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose")
        self._downgrade_state()
        self.sb.tick(self.sb.proposal_path(), "promote-global:lock-before-write", "approve")
        r = self.sb.run("apply-promotions", check=False)
        self.assertIn("re-proposed", r.stderr)
        r = self.sb.run("propose")
        self.assertIn("promote-global:lock-before-write", self._ids(), r.stdout + r.stderr)
        entry = json.load(open(self.ledger_path))["promote-global:lock-before-write"]
        self.assertEqual(entry["status"], "proposed")
        self.assertIn("rendered_sha256", entry)

    def test_notes_that_claim_to_be_his_are_listed_once_for_him_to_confirm(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", TRIG, "--action", ACTION,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        self.sb.run("propose")  # an existing install has a ledger
        self._downgrade_state()
        r = self.sb.run("propose")
        self.assertIn("confirm-stated:notes", self._ids(), r.stdout + r.stderr)
        text = open(self.sb.proposal_path(), encoding="utf-8").read()
        refs = re.findall(r"^- \[ \] confirm `([^`]+)`$", text, re.M)
        self.assertEqual(len(refs), 2)
        # He confirms both lines and approves the block.
        text = text.replace("- [ ] confirm `", "- [x] confirm `")
        open(self.sb.proposal_path(), "w", encoding="utf-8").write(text)
        self.sb.tick(self.sb.proposal_path(), "confirm-stated:notes", "approve")
        self.sb.run("apply-promotions")
        stated = json.load(open(os.path.join(self.state, "user-stated.json")))
        self.assertEqual(sorted(stated), sorted(refs))
        r = self.sb.run("propose")
        self.assertIn("promote-global:lock-before-write", self._ids(), r.stdout + r.stderr)
        self.assertEqual(self._ids().count("confirm-stated:notes"), 1, "the confirm block was filed again")

    def test_add_restate_re_vouches_a_note_he_edited(self):
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--id", "lock-before-write", "--trigger", TRIG, "--action", ACTION,
                        "--domain", "code-style", "--confidence", "0.9", cwd=repo)
        root = os.path.join(self.sb.vault, "06 Memory", "instincts", "project")
        for pid in os.listdir(root):
            p = os.path.join(root, pid, "lock-before-write.md")
            open(p, "a", encoding="utf-8").write("\nAlso hold the lock while rotating the file.\n")
        r = self.sb.run("propose")
        self.assertNotIn("promote-global:lock-before-write", self._ids())
        for repo in ("repoA", "repoB"):
            self.sb.run("add", "--restate", "lock-before-write", cwd=repo)
        r = self.sb.run("propose")
        self.assertIn("promote-global:lock-before-write", self._ids(), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
