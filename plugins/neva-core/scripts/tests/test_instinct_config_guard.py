#!/usr/bin/env python3
"""Inside the global config folder the engine writes only what it is allowed to, whatever the spelling.

The old guard compared path parts case-sensitively and resolved only the destination, so on a
case-insensitive disk `Commands/evil.md` landed in `commands/`, and a `skills` folder linked
elsewhere was not seen as global at all. The guard is now an allow-list: without the evolve opt-in
the only global files the engine may write are rules/instincts-*.md; with it, also one skill,
command or agent file. Nothing else in the folder (CLAUDE.md, settings.json, hooks) is ever a
destination, and a registered project's .claude takes skills, commands and agents only.

Every write lands in a temporary config folder and vault.

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/neva-core/scripts/tests
"""
import os
import re
import unittest

from test_instinct_learning import InstinctSandbox

FLAG = "NEVA_INSTINCT_EVOLVE"
BID = "rule:explicit-errors"


class ConfigGuardCase(unittest.TestCase):
    def setUp(self):
        self.sb = InstinctSandbox()
        self.addCleanup(self.sb.close)
        self.config = os.path.join(self.sb.tmp, "claude-config")
        os.makedirs(self.config)
        self.env = {"CLAUDE_CONFIG_DIR": self.config}
        self.sb.run("add", "--id", "explicit-errors", "--trigger", "when handling errors in services",
                    "--action", "Return a typed error naming the field and the fix.", "--domain", "code-style",
                    "--confidence", "0.95", "--scope", "global", env=self.env)
        self.sb.run("propose", env=self.env)

    def _redirect(self, dest):
        path = self.sb.proposal_path()
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        start = text.index(f"block_id: {BID}")
        row = re.compile(r"^\| Proposed destination \| .* \|$", re.M).search(text, start)
        text = text[:row.start()] + f"| Proposed destination | `{dest}` |" + text[row.end():]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.sb.tick(path, BID, "approve")

    def _apply(self, flag=False):
        env = dict(self.env, **({FLAG: "1"} if flag else {}))
        return self.sb.run("apply-promotions", check=False, env=env)

    def _written(self, root=None):
        root = root or self.config
        return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)

    def test_mixed_case_does_not_reach_commands(self):
        self._redirect(os.path.join(self.config, "Commands", "evil.md"))
        r = self._apply()
        self.assertEqual(self._written(), [], r.stdout + r.stderr)
        self.assertIn(BID, r.stderr)
        self.assertIn("Fix:", r.stderr)

    def test_dot_dot_segments_do_not_reach_commands(self):
        self._redirect(os.path.join(self.config, "rules", "..", "commands", "evil.md"))
        r = self._apply()
        self.assertEqual(self._written(), [], r.stdout + r.stderr)

    def test_a_linked_skills_folder_is_still_the_config_folder(self):
        elsewhere = os.path.join(self.sb.vault, "linked-skills")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.config, "skills"))
        self._redirect(os.path.join(self.config, "skills", "evil", "SKILL.md"))
        r = self._apply()
        self.assertEqual(self._written(elsewhere), [], r.stdout + r.stderr)

    def test_the_global_claude_md_is_never_a_destination(self):
        self._redirect(os.path.join(self.config, "CLAUDE.md"))
        r = self._apply(flag=True)
        self.assertEqual(self._written(), [], r.stdout + r.stderr)

    def test_settings_are_never_a_destination_even_with_the_opt_in(self):
        self._redirect(os.path.join(self.config, "Settings.json"))
        r = self._apply(flag=True)
        self.assertEqual(self._written(), [], r.stdout + r.stderr)

    def test_a_project_settings_file_is_never_a_destination(self):
        self.sb.run("status", env=self.env)  # registers repoA
        self._redirect(os.path.join(self.sb.repos["repoA"], ".claude", "settings.json"))
        r = self._apply(flag=True)
        self.assertFalse(os.path.exists(os.path.join(self.sb.repos["repoA"], ".claude", "settings.json")),
                         r.stdout + r.stderr)

    def test_the_rule_file_is_still_written_without_the_opt_in(self):
        self.sb.tick(self.sb.proposal_path(), BID, "approve")
        r = self._apply()
        self.assertEqual(self._written(), [os.path.join("rules", "instincts-code-style.md")], r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
