#!/usr/bin/env python3
"""Automatic evolution into commands, agents and keyword-matched skills is off unless asked for.

Every workflow instinct at 0.70 used to become a slash command, and any two instincts sharing two
trigger words a skill, which filled the global config folder with commands whose whole job was a
shell habit. These tests prove propose emits no evolve block by default, `evolve --propose` refuses
without the opt-in, apply refuses to write a skill, command or agent into the global config folder
without it, and the opt-in brings the old behaviour back. Every write lands in a temporary config
folder: nothing here touches a real one.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

FLAG = "NEVA_INSTINCT_EVOLVE"


class EvolveOptInCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.config = os.path.join(self.sb.tmp, "claude-config")
        os.makedirs(self.config)
        self.env = {"CLAUDE_CONFIG_DIR": self.config}

    HABITS = [
        ("when opening a pull request", "Link the issue and list the manual checks performed."),
        ("when rotating staging secrets", "Revoke the previous credential after the new one verifies."),
        ("when a migration drops a column", "Ship the reader change one release before removing it."),
        ("when bumping a dependency", "Read its changelog entries between both versions first."),
        ("when tagging a release", "Confirm the changelog heading matches the version number."),
        ("when a flaky assertion appears", "Quarantine that case and file an owner with a deadline."),
        ("when adding a cron schedule", "State the timezone explicitly beside the expression."),
        ("when renaming a public function", "Keep a deprecated alias for one minor version."),
        ("when touching payment rounding", "Compute in integer cents and round only at display."),
        ("when writing a shell installer", "Abort on unset variables and print each failing step."),
    ]

    def _workflow_instincts(self, scope="project", n=10):
        # Ten unrelated habits, each a real behaviour, so the quality gate passes every one.
        for i, (trigger, action) in enumerate(self.HABITS[:n]):
            self.sb.run("add", "--id", f"habit-{i}", "--trigger", trigger,
                        "--action", action, "--domain", "workflow", "--confidence", "0.9",
                        "--scope", scope, env=self.env)

    def _ids(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

    def _tick_evolve(self):
        for bid in self._ids():
            if bid.startswith("evolve-"):
                self.sb.tick(self.sb.proposal_path(), bid, "approve")

    def _config_files(self):
        return sorted(os.path.relpath(os.path.join(d, f), self.config)
                      for d, _, files in os.walk(self.config) for f in files)

    def test_propose_emits_no_evolve_block_by_default(self):
        self._workflow_instincts()
        self.sb.run("propose", "--limit", "0", env=self.env)
        evolved = [i for i in self._ids() if i.startswith("evolve-")]
        self.assertEqual(evolved, [], f"evolve blocks proposed without {FLAG}=1")

    def test_the_opt_in_brings_evolve_blocks_back(self):
        self._workflow_instincts()
        self.sb.run("propose", "--limit", "0", env=dict(self.env, **{FLAG: "1"}))
        self.assertTrue(any(i.startswith("evolve-command:") for i in self._ids()))

    def test_evolve_propose_refuses_without_the_opt_in(self):
        self._workflow_instincts()
        r = self.sb.run("evolve", "--propose", check=False, env=self.env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(FLAG, r.stderr)
        self.assertIn("Fix:", r.stderr)
        self.assertEqual(self._ids(), [])

    def test_apply_refuses_to_write_into_the_global_config_folder_without_the_opt_in(self):
        self._workflow_instincts(scope="global", n=3)
        self.sb.run("propose", "--limit", "0", env=dict(self.env, **{FLAG: "1"}))
        self.assertTrue(any(i.startswith("evolve-") for i in self._ids()), "fixture made no evolve block")
        self._tick_evolve()
        r = self.sb.run("apply-promotions", check=False, env=self.env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(FLAG, r.stderr)
        evolved = [f for f in self._config_files() if f.split(os.sep)[0] in ("skills", "commands", "agents")]
        self.assertEqual(evolved, [], "an evolved file was written into the global config folder")

    def test_apply_writes_into_the_global_config_folder_with_the_opt_in(self):
        self._workflow_instincts(scope="global", n=3)
        self.sb.run("propose", "--limit", "0", env=dict(self.env, **{FLAG: "1"}))
        self._tick_evolve()
        self.sb.run("apply-promotions", env=dict(self.env, **{FLAG: "1"}))
        self.assertTrue(any(f.startswith("commands/") for f in self._config_files()), self._config_files())


if __name__ == "__main__":
    unittest.main()
