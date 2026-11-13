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

    def _workflow_instincts(self, scope="project", n=10):
        for i in range(n):
            self.sb.run("add", "--id", f"habit-{i}", "--trigger", f"when step {i} of the release checklist runs",
                        "--action", "Do the thing.", "--domain", "workflow", "--confidence", "0.9",
                        "--scope", scope, env=self.env)

    def _ids(self):
        path = self.sb.proposal_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return re.findall(r"<!-- block_id: (\S+) -->", fh.read())

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
        r = self.sb.run("apply-promotions", "--all", check=False, env=self.env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(FLAG, r.stderr)
        evolved = [f for f in self._config_files() if f.split(os.sep)[0] in ("skills", "commands", "agents")]
        self.assertEqual(evolved, [], "an evolved file was written into the global config folder")

    def test_apply_writes_into_the_global_config_folder_with_the_opt_in(self):
        self._workflow_instincts(scope="global", n=3)
        self.sb.run("propose", "--limit", "0", env=dict(self.env, **{FLAG: "1"}))
        self.sb.run("apply-promotions", "--all", env=dict(self.env, **{FLAG: "1"}))
        self.assertTrue(any(f.startswith("commands/") for f in self._config_files()), self._config_files())


if __name__ == "__main__":
    unittest.main()
