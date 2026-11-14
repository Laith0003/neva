#!/usr/bin/env python3
"""Small fail-closed fixes in the learning engine, one class per finding.

  CorpusSizeCase      the quality gate skips (and names) a rules or memory file over the size cap
  LedgerIdLinkCase    the vault's .ledger-id is never read or written through a symlink
  NoMembersCase       a block with nothing to check fails closed unless its kind may have none
  OneRepoCase         one repo under two bucket ids is one project, not two
  BindingRaceCase     the vault id is created exclusively and the winner is what the state records
  SyncedVaultCase     the refusal on a new machine names NEVA_INSTINCT_NEW_LEDGER=1

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone

from test_instinct_learning import LEARNING_SCRIPTS, InstinctSandbox
from test_instinct_rule_text import _module

sys.path.insert(0, LEARNING_SCRIPTS)
import quality_gate  # noqa: E402


class CorpusSizeCase(unittest.TestCase):
    def test_a_file_over_the_cap_is_skipped_and_named(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        rules = os.path.join(sb.tmp, "rules")
        os.makedirs(rules)
        with open(os.path.join(rules, "small.md"), "w", encoding="utf-8") as fh:
            fh.write("Return a typed error that names the field and how to fix it.\n")
        with open(os.path.join(rules, "huge.md"), "w", encoding="utf-8") as fh:
            fh.write("Take an exclusive lock before appending to the shared ledger file.\n\n")
            fh.write(("filler words for the size cap " * 40 + "\n\n") * 300)
        skipped = []
        units = quality_gate.load_corpus([rules], skipped=skipped)
        self.assertEqual({label for label, _ in units}, {"rule small.md"})
        self.assertEqual([os.path.basename(p) for p in skipped], ["huge.md"])
        self.assertGreater(os.path.getsize(os.path.join(rules, "huge.md")), quality_gate.MAX_CORPUS_FILE_BYTES)


class LedgerIdLinkCase(unittest.TestCase):
    def test_a_linked_ledger_id_is_refused(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        link = os.path.join(sb.vault, "06 Memory", "instincts", ".ledger-id")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(os.path.join(sb.tmp, "elsewhere-id"), link)
        r = sb.run("propose", check=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("symlink", r.stderr)
        self.assertIn(".ledger-id", r.stderr)
        self.assertTrue(os.path.islink(link), "the link was replaced instead of refused")


class NoMembersCase(unittest.TestCase):
    def test_a_rule_block_with_no_members_fails_closed(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        cli = _module(sb)
        bare = cli._block("rule", "x", [("Kind", "rule")], "text")
        retire = cli._block("retire", "y", [("Kind", "retire")], "status: archived\n")
        passed = cli._gate([bare, retire], dry_run=True)
        self.assertEqual([b['block_id'] for b in passed], ["retire:y"])
        self.assertEqual(cli.NO_MEMBER_KINDS, ("retire", "confirm-stated"))


class OneRepoCase(unittest.TestCase):
    def test_one_repo_under_two_bucket_ids_is_one_project(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        registry = os.path.join(sb.tmp, "data", "neva", "observations", "projects.json")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # The same repo, registered once before its origin remote was added and once after.
        reg = {pid: {"id": pid, "name": "repoA", "root": sb.repos["repoA"], "remote": "",
                     "created_at": now, "last_seen": now} for pid in ("aaaaaaaaaaa1", "aaaaaaaaaaa2")}
        os.makedirs(os.path.dirname(registry), exist_ok=True)
        with open(registry, "w") as fh:
            json.dump(reg, fh)
        from test_instinct_evidence import ACTION, NOTE, S1, S2, TODAY, YESTERDAY
        for pid in reg:
            d = os.path.join(sb.vault, "06 Memory", "instincts", "project", pid)
            os.makedirs(d)
            with open(os.path.join(d, "lock-before-write.md"), "w", encoding="utf-8") as fh:
                fh.write(NOTE.format(source="session-observation", pid=pid, name="repoA", first=YESTERDAY,
                                     last=TODAY, s1=S1, s2=S2, action=ACTION))
            sb.observe(pid, [(S1, str(YESTERDAY)), (S2, str(TODAY))])
        r = sb.run("propose", cwd=sb.home)
        text = open(sb.proposal_path(), encoding="utf-8").read() if os.path.exists(sb.proposal_path()) else ""
        self.assertNotIn("promote-global:lock-before-write", text, r.stdout + r.stderr)


class BindingRaceCase(unittest.TestCase):
    def test_the_vault_id_is_claimed_exclusively_and_the_winner_kept(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        cli = _module(sb)
        vault_file = os.path.join(sb.vault, "06 Memory", "instincts", ".ledger-id")
        os.makedirs(os.path.dirname(vault_file), exist_ok=True)
        with open(vault_file, "w") as fh:
            fh.write("winner0000000001\n")
        self.assertEqual(cli._claim_vault_id("loser00000000002"), "winner0000000001")
        with open(vault_file) as fh:
            self.assertEqual(fh.read().strip(), "winner0000000001")
        os.remove(vault_file)
        self.assertEqual(cli._claim_vault_id("fresh00000000003"), "fresh00000000003")


class SyncedVaultCase(unittest.TestCase):
    def test_the_refusal_names_the_new_ledger_switch(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        fresh = os.path.join(sb.tmp, "new-machine-state")
        os.makedirs(fresh)
        r = sb.run("propose", check=False, env={"XDG_STATE_HOME": fresh})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NEVA_INSTINCT_NEW_LEDGER=1", r.stderr)


class RevertGuardCase(unittest.TestCase):
    """Fail if 150e818 (exclusive vault id) or 4bc8bf9 (no-member blocks fail closed) is reverted."""

    def test_a_run_that_loses_the_race_records_the_winner_not_its_own_id(self):
        from unittest import mock
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        sb.add("repoA", "seed", 0.9)
        cli = _module(sb)
        vault_file = os.path.join(sb.vault, "06 Memory", "instincts", ".ledger-id")
        with open(vault_file, "w") as fh:
            fh.write("winner0000000001\n")
        real = cli._read_vault_id
        calls = []

        def first_read_misses():
            calls.append(1)
            return None if len(calls) == 1 else real()  # the other run wrote it just after our read
        with mock.patch.dict(os.environ, sb.env, clear=True), mock.patch.object(cli, "_read_vault_id", first_read_misses):
            cli._check_state_binding(write=True)
        self.assertEqual(open(vault_file).read().strip(), "winner0000000001", "the winner's id was overwritten")
        state = json.load(open(os.path.join(sb.tmp, "state", "neva", "instincts", "vault-binding.json")))
        self.assertEqual(state["ledger_id"], "winner0000000001")

    def test_an_evolve_block_with_no_members_is_parked_with_its_reason(self):
        sb = InstinctSandbox()
        self.addCleanup(sb.close)
        cli = _module(sb)
        from unittest import mock
        bare = cli._block("evolve-command", "x", [("Kind", "evolve-command")], "text")
        with mock.patch.dict(os.environ, sb.env, clear=True):
            passed = cli._gate([bare], dry_run=False)
        self.assertEqual(passed, [])
        parked = json.load(open(os.path.join(sb.tmp, "state", "neva", "instincts", "parked.json")))
        self.assertIn("no instincts to check", " ".join(parked["evolve-command:x"]["reasons"]))


if __name__ == "__main__":
    unittest.main()
