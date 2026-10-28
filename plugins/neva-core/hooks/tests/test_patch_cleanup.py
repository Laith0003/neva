# Uses the harness adapted from affaan-m/ECC (MIT), commit d3b8a3e.
"""Regression tests for untrusted patch metadata and mixed-config hunk placement."""
import unittest
from test_hooks import HookTest, common


class TestPatchCleanup(HookTest):
    def call(self, name, inp, harness="codex"):
        return self.s.dispatch("PreToolUse", self.base(tool_name=name, tool_input=inp),
                               NEVA_HARNESS=harness)

    def patch(self, text, hunk):
        fp = self.s.write("work/proj/pyproject.toml", text)
        return self.call("apply_patch", "*** Begin Patch\n*** Update File: " + fp +
                         "\n" + hunk + "*** End Patch\n")

    def test_model_supplied_hunks_cannot_hide_a_lint_edit(self):
        fp = self.s.write("work/proj/pyproject.toml", '[tool.ruff]\nignore = []\n')
        for harness in ("codex", "claude", "opencode"):
            with self.subTest(harness=harness):
                self.assertBlocked(self.call("Edit", {"file_path": fp,
                    "old_string": "ignore = []", "new_string": 'ignore = ["F401"]',
                    "neva_hunks": [{"old_string": "safe", "new_string": "fine"}]}, harness),
                    "ignore")

    def test_pure_addition_checks_both_anchor_and_eof(self):
        for text, anchor in (('[project]\nname = "x"\n[tool.ruff]\n', '[project]'),
                             ('[tool.ruff]\n[project]\nname = "x"\n', '[tool.ruff]')):
            with self.subTest(anchor=anchor):
                self.assertBlocked(self.patch(text, '@@ ' + anchor + '\n+ignore = ["F401"]\n'), "ignore")

    def test_unlocatable_mixed_config_hunk_is_guarded(self):
        self.assertBlocked(self.patch('[project]\nname = "x"\n',
            '@@\n-not actually present\n+ignore = ["F401"]\n'), "ignore")

    def test_whitespace_tolerant_hunks_keep_lint_section(self):
        for old in ('ignore = []', '   ignore = []'):
            with self.subTest(old=old):
                self.assertBlocked(self.patch('[project]\nname = "x"\n[tool.ruff]\nignore = []   \n',
                    '@@\n-' + old + '\n+ignore = ["F401"]\n'), "ignore")

    def test_non_lint_addition_remains_allowed(self):
        self.assertAllowed(self.patch('[project]\nname = "x"\n',
            '@@ [project]\n+ignore = ["docs"]\n'))

    def test_normalization_removes_incoming_reserved_metadata(self):
        for harness in ("codex", "claude", "opencode"):
            _, data, _ = common.normalize_payload("PreToolUse", {"tool_name": "Edit",
                "tool_input": {"neva_hunks": [], "neva_other": "spoof", "old_string": "x"}}, harness)
            self.assertEqual(data["tool_input"], {"old_string": "x"})


if __name__ == "__main__":
    unittest.main()
