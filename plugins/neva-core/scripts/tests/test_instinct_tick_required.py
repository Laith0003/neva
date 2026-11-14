#!/usr/bin/env python3
"""No command writes an approval without a tick (issue 27, B2).

`apply-promotions --all` applies, without a tick, only the kinds that write inside the vault and
carry no approval with them: retire blocks. A promote-global block (a global note, which the
engine then trusts as approved), a rule or evolve block (the global config folder) and a
confirm-stated block (the add ledger) wait for the human's tick whatever flag is passed.
`promote <id> --apply` files the block and stops.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import unittest

from test_instinct_learning import InstinctSandbox


class TickRequiredCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.instincts = os.path.join(self.sb.vault, "06 Memory", "instincts")
        self.rules = os.path.join(self.sb.home, ".claude", "rules")

    def proposal(self):
        with open(self.sb.proposal_path(), encoding="utf-8") as fh:
            return fh.read()

    def global_note(self, iid):
        return os.path.join(self.instincts, "global", f"{iid}.md")

    def test_all_does_not_apply_an_unticked_promote_global_block(self):
        self.sb.add("repoA", "lock-before-write", 0.9)
        self.sb.run("promote", "lock-before-write")
        self.assertIn("block_id: promote-global:lock-before-write", self.proposal())
        r = self.sb.run("apply-promotions", "--all", check=False)
        self.assertFalse(os.path.exists(self.global_note("lock-before-write")), r.stdout + r.stderr)
        self.assertIn("promote-global:lock-before-write", r.stdout + r.stderr)
        self.assertIn("Fix: tick", r.stdout + r.stderr)
        # The block stays open for the tick.
        self.sb.tick(self.sb.proposal_path(), "promote-global:lock-before-write", "approve")
        self.sb.run("apply-promotions")
        self.assertTrue(os.path.exists(self.global_note("lock-before-write")))

    def test_all_does_not_write_an_unticked_rule_into_the_config_folder(self):
        self.sb.run("add", "--id", "explicit-errors", "--trigger", "when handling errors in services",
                    "--action", "Return a typed error naming the field and the fix.",
                    "--domain", "code-style", "--confidence", "0.95", "--scope", "global")
        self.sb.run("propose")
        self.assertIn("block_id: rule:explicit-errors", self.proposal())
        self.sb.run("apply-promotions", "--all", check=False)
        self.assertFalse(os.path.exists(os.path.join(self.rules, "instincts-code-style.md")))
        self.assertNotIn("Applied ", self.proposal().split("block_id: rule:explicit-errors", 1)[1].split("## ", 1)[0])

    def test_all_does_not_record_an_unticked_confirm_stated_block(self):
        # An install from before the add ledger: notes that say source: user-stated, no ledger rows.
        # propose lists them in one confirm-stated block; only his tick records them.
        for repo in ("repoA", "repoB"):
            self.sb.add(repo, "lock-before-write", 0.9)
        self.sb.run("propose")
        stated = os.path.join(self.sb.tmp, "state", "neva", "instincts", "user-stated.json")
        os.remove(stated)
        self.sb.run("propose")
        self.assertIn("block_id: confirm-stated:notes", self.proposal())
        text = self.proposal().replace("- [ ] confirm `", "- [x] confirm `")
        with open(self.sb.proposal_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        r = self.sb.run("apply-promotions", "--all", check=False)
        rows = json.load(open(stated)) if os.path.exists(stated) else {}
        self.assertEqual(rows, {}, r.stdout + r.stderr)

    def test_all_still_applies_an_unticked_retire_block(self):
        self.sb.add("repoA", "fading-lesson", 0.2)
        self.sb.run("propose")
        text = self.proposal()
        bid = next(line.split("block_id: ", 1)[1].split(" ", 1)[0] for line in text.splitlines()
                   if "block_id: retire:" in line)
        r = self.sb.run("apply-promotions", "--all", check=False)
        self.assertIn("Applied 1", r.stdout, r.stdout + r.stderr)
        note = next(os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(self.instincts, "project"))
                    for f in fs if f == "fading-lesson.md")
        self.assertIn("status: archived", open(note, encoding="utf-8").read(), bid)

    def test_promote_apply_files_the_block_and_stops(self):
        self.sb.add("repoA", "lock-before-write", 0.9)
        r = self.sb.run("promote", "lock-before-write", "--apply", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.global_note("lock-before-write")))
        self.assertIn("block_id: promote-global:lock-before-write", self.proposal())
        self.assertIn("tick", r.stdout + r.stderr)
        self.sb.tick(self.sb.proposal_path(), "promote-global:lock-before-write", "approve")
        self.sb.run("apply-promotions")
        self.assertTrue(os.path.exists(self.global_note("lock-before-write")))


if __name__ == "__main__":
    unittest.main()
