# Tests for the Neva runtime adapted from affaan-m/ECC (MIT), commit d3b8a3e.
"""Native harness edit schemas exercised through the installed hook runtime."""
import os
import unittest
from test_hooks import HookTest


class TestNativeEditContent(HookTest):
    def call(self, harness, name, arguments):
        return self.s.dispatch("PreToolUse", self.base(tool_name=name, tool_input=arguments),
                               NEVA_HARNESS=harness)

    def config(self):
        return self.s.write("work/proj/tsconfig.json", '{"strict": true}\n')

    def test_edit_shapes_protect_strictness(self):
        fp = self.config()
        for harness, name, args in (
            ("claude", "Edit", {"file_path": fp, "old_string": '"strict": true', "new_string": '"strict": false'}),
            ("opencode", "edit", {"filePath": fp, "oldString": '"strict": true', "newString": '"strict": false'}),
            ("opencode", "multiedit", {"filePath": fp, "edits": [{"oldString": '"strict": true', "newString": '"strict": false'}]}),
        ):
            with self.subTest(harness=harness, name=name):
                self.assertBlocked(self.call(harness, name, args), "strictness flag")
                self.assertEqual(self.s.read(fp), '{"strict": true}\n')

    def patch(self, fp, new='false'):
        return '*** Begin Patch\n*** Update File: ' + fp + '\n@@\n-{"strict": true}\n+{"strict": ' + new + '}\n*** End Patch\n'

    def test_patch_content_checked_per_target(self):
        fp = self.config()
        harmless = os.path.join(self.s.work, "a.txt")
        patch = self.patch(fp).replace('*** Begin Patch\n', '*** Begin Patch\n*** Add File: ' + harmless + '\n+hello\n')
        for harness, key in (("codex", "command"), ("opencode", "patchText")):
            with self.subTest(harness=harness):
                self.assertBlocked(self.call(harness, "apply_patch", {key: patch}), "strictness flag")
                self.assertEqual(self.s.read(fp), '{"strict": true}\n')
                self.assertFalse(os.path.exists(harmless))

    def test_harmless_native_edits_allowed(self):
        fp = self.config()
        self.assertAllowed(self.call("opencode", "edit", {"filePath": fp, "oldString": 'true', "newString": 'true'}))
        self.assertAllowed(self.call("opencode", "apply_patch", {"patchText": self.patch(fp, "true")}))

    def test_opencode_patchtext_vault_target_blocked(self):
        self.assertBlocked(self.call("opencode", "apply_patch", {"patchText": self.patch(os.path.join(self.s.vault, "GOALS.md"), "true")}), "GOALS.md")

    def pyproject(self):
        return self.s.write("work/proj/pyproject.toml",
                            '[project]\nname = "x"\nversion = "1.0"\n\n[tool.mypy]\nstrict = true\n')

    def two_hunks(self, fp, strict="false"):
        return ("*** Begin Patch\n*** Update File: " + fp + "\n"
                '@@ [project]\n name = "x"\n-version = "1.0"\n+version = "1.1"\n'
                "@@ [tool.mypy]\n-strict = true\n+strict = " + strict + "\n*** End Patch\n")

    def test_two_hunk_patch_on_mixed_config_is_judged_per_hunk(self):
        fp = self.pyproject()
        for harness, key in (("codex", "command"), ("opencode", "patchText")):
            with self.subTest(harness=harness):
                self.assertBlocked(self.call(harness, "apply_patch", {key: self.two_hunks(fp)}), "strictness flag")
                self.assertAllowed(self.call(harness, "apply_patch", {key: self.two_hunks(fp, "true")}))

    def test_pure_addition_hunk_uses_its_section_anchor(self):
        fp = self.pyproject()
        patch = ("*** Begin Patch\n*** Update File: " + fp + "\n@@ [tool.mypy]\n+ignore_missing_imports = true\n"
                 "*** End Patch\n")
        self.assertBlocked(self.call("codex", "apply_patch", {"command": patch}), "ignore")
        harmless = patch.replace("@@ [tool.mypy]", "@@ [project]").replace("ignore_missing_imports = true",
                                                                           'description = "y"')
        self.assertAllowed(self.call("codex", "apply_patch", {"command": harmless}))

    def test_starred_context_line_is_content_not_a_header(self):
        notes = self.s.write("work/proj/notes.md", "*** Draft notes ***\nold\n")
        patch = ("*** Begin Patch\n*** Update File: " + notes + "\n@@\n *** Draft notes ***\n-old\n+new\n"
                 "*** End Patch\n")
        self.assertAllowed(self.call("codex", "apply_patch", {"command": patch}))
        goals = os.path.join(self.s.vault, "GOALS.md")
        after = patch.replace("*** End Patch", "*** Update File: " + goals + "\n@@\n-a\n+b\n*** End Patch")
        self.assertBlocked(self.call("codex", "apply_patch", {"command": after}), "GOALS.md")


if __name__ == "__main__":
    unittest.main()
