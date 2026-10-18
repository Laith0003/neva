# Tests for the Neva runtime adapted from affaan-m/ECC (MIT), commit d3b8a3e.
"""OpenCode apply_patch uses the native patchText argument."""
import os
from pathlib import Path
import unittest
from test_hooks import HookTest

class TestNativePatchText(HookTest):
    def test_native_patchtext_allows_plain_target_and_blocks_protected_target(self):
        for target, blocked in ((os.path.join(self.s.work, "a.txt"), False),
                                (os.path.join(self.s.vault, "GOALS.md"), True)):
            before = Path(target).read_bytes() if os.path.exists(target) else None
            patch = "*** Begin Patch\n*** Add File: " + target + "\n+hello\n*** End Patch\n"
            result = self.s.dispatch("PreToolUse", self.base(tool_name="apply_patch", tool_input={"patchText": patch}), NEVA_HARNESS="opencode")
            if result.code == 0:
                # What the harness does next: an allowed patch is applied, a blocked one is not.
                Path(target).write_bytes(b"hello\n")
            after = Path(target).read_bytes() if os.path.exists(target) else None
            if blocked:
                self.assertBlocked(result, "GOALS.md")
                self.assertEqual(before, after)
            else:
                self.assertAllowed(result)
                self.assertIsNone(before)
                self.assertEqual(b"hello\n", after)
                self.assertIn(target, [r.get("path") for r in self.s.obs_lines()],
                              "observe must record the patchText target as the tool path")


if __name__ == "__main__":
    unittest.main()
