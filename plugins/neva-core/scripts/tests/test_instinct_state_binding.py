#!/usr/bin/env python3
"""The promotion ledger and the project registry are bound to the vault they were used with.

A propose run that points at a vault but reads an empty or foreign ledger, or an empty registry,
would propose again every block the human already applied or still has open, and would send
project blocks to the global config folder. These tests prove such a run refuses, names the
variable and the fix, and leaves every file in the vault byte for byte as it was.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import json
import os
import unittest

from test_instinct_learning import InstinctSandbox


def _snapshot(root):
    snap = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as fh:
                snap[os.path.relpath(p, root)] = fh.read()
    return snap


class StateBindingCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)

    def _seed(self):
        """One applied block and one open block in the vault, both known to the real ledger."""
        sb = self.sb
        sb.add("repoA", "prefer-explicit-errors", 0.9)
        sb.add("repoB", "prefer-explicit-errors", 0.85)
        sb.run("propose")
        sb.tick(sb.proposal_path(), "promote-global:prefer-explicit-errors", "approve")
        sb.run("apply-promotions")
        sb.add("repoA", "avoid-mocks", 0.9, trigger="when writing tests for a service layer")
        sb.add("repoB", "avoid-mocks", 0.85, trigger="when writing tests for a service layer")
        sb.run("propose")
        # Age the file to an earlier day, as the real queue is: the blocks now live in a file
        # that is not today's, so only the ledger or the vault itself can say they exist.
        today = sb.proposal_path()
        older = os.path.join(os.path.dirname(today), "Instinct promotions 2020-01-01.md")
        os.rename(today, older)
        ledger_path = os.path.join(sb.tmp, "state", "neva", "instincts", "promotions.json")
        with open(ledger_path) as fh:
            ledger = json.load(fh)
        for entry in ledger.values():
            if isinstance(entry, dict) and entry.get("file") == today:
                entry["file"] = older
        with open(ledger_path, "w") as fh:
            json.dump(ledger, fh)
        self.older = older

    def _other(self, name):
        path = os.path.join(self.sb.tmp, name)
        os.makedirs(path, exist_ok=True)
        return path

    def test_an_empty_state_folder_refuses_and_writes_nothing(self):
        self._seed()
        before = _snapshot(self.sb.vault)
        r = self.sb.run("propose", check=False, env={"XDG_STATE_HOME": self._other("fresh-state")})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NEVA_STATE_DIR", r.stderr)
        self.assertIn("Fix:", r.stderr)
        self.assertEqual(_snapshot(self.sb.vault), before, "the vault changed under a foreign ledger")

    def test_a_ledger_bound_to_another_vault_is_refused(self):
        self._seed()
        other_vault = self._other("other-vault")
        os.makedirs(os.path.join(other_vault, "00 Inbox"))
        r = self.sb.run("propose", check=False, env={"NEVA_VAULT": other_vault})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NEVA_VAULT", r.stderr)
        self.assertIn("Fix:", r.stderr)
        self.assertEqual(_snapshot(other_vault), {}, "a proposal was written into the other vault")

    def test_a_foreign_state_folder_is_refused_after_binding(self):
        self._seed()
        foreign = self._other("foreign-state")
        # A ledger that has history of its own, bound to nothing.
        os.makedirs(os.path.join(foreign, "neva", "instincts"))
        with open(os.path.join(foreign, "neva", "instincts", "promotions.json"), "w") as fh:
            json.dump({"promote-global:something-else": {"status": "applied", "file": "x", "date": "2026-01-01"}}, fh)
        before = _snapshot(self.sb.vault)
        r = self.sb.run("propose", check=False, env={"XDG_STATE_HOME": foreign})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NEVA_STATE_DIR", r.stderr)
        self.assertEqual(_snapshot(self.sb.vault), before)

    def test_a_new_ledger_on_purpose_never_proposes_a_block_already_in_the_vault(self):
        self._seed()
        r = self.sb.run("propose", env={"XDG_STATE_HOME": self._other("fresh-state"),
                                         "NEVA_INSTINCT_NEW_LEDGER": "1"})
        self.assertFalse(os.path.exists(self.sb.proposal_path()),
                         f"blocks already in an older file were proposed again:\n{r.stdout}")

    def test_an_empty_registry_with_project_buckets_is_refused(self):
        self._seed()
        before = _snapshot(self.sb.vault)
        r = self.sb.run("propose", check=False, env={"XDG_DATA_HOME": self._other("fresh-data")})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NEVA_DATA_DIR", r.stderr)
        self.assertIn("Fix:", r.stderr)
        self.assertEqual(_snapshot(self.sb.vault), before)

    def test_an_unknown_project_root_never_falls_back_to_the_global_config_folder(self):
        sb = self.sb
        config = self._other("claude-config")
        env = {"CLAUDE_CONFIG_DIR": config, "NEVA_INSTINCT_EVOLVE": "1"}
        for n, words in enumerate(("deploying the staging site", "rotating staging secrets",
                                    "reading the staging logs")):
            sb.add("repoA", f"habit-{n}", 0.9, domain="workflow", trigger=f"when {words}")
        sb.add("repoB", "unrelated", 0.5)
        registry_path = os.path.join(sb.tmp, "data", "neva", "observations", "projects.json")
        with open(registry_path) as fh:
            registry = json.load(fh)
        lost = [pid for pid, info in registry.items() if info.get("name") == "repoA"]
        self.assertEqual(len(lost), 1)
        del registry[lost[0]]
        with open(registry_path, "w") as fh:
            json.dump(registry, fh)
        # Run from outside any repo so the run itself does not register repoA again.
        r = sb.run("propose", check=False, env=env, cwd=sb.home)
        text = ""
        if os.path.exists(sb.proposal_path()):
            with open(sb.proposal_path(), encoding="utf-8") as fh:
                text = fh.read()
        self.assertNotIn(config, text, "a project block was pointed at the global config folder")
        self.assertNotIn("~/.claude", text, "a project block was pointed at the global config folder")
        self.assertIn(lost[0], r.stderr, "the skipped project must be named")
        self.assertIn("Fix:", r.stderr)


if __name__ == "__main__":
    unittest.main()
