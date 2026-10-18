# Tests for the Neva runtime adapted from affaan-m/ECC (MIT), commit d3b8a3e.
"""Foreign PreToolUse dispatcher failures must block before any guard is skipped."""
import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch


class TestDispatchFailures(unittest.TestCase):
    def invoke(self, raw, harness="codex", event="PreToolUse"):
        with patch.dict(os.environ, {"NEVA_HARNESS": harness, "NEVA_HEADLESS": "0"}), \
             patch.object(sys, "stdin", io.StringIO(raw)), \
             patch.object(dispatch.common, "log"), \
             patch.object(dispatch.common, "log_exception"), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            code = dispatch.entrypoint(["dispatch.py", event])
        return code, out.getvalue(), err.getvalue()

    def test_malformed_missing_array_and_oversized_payloads_block(self):
        for harness in ("codex", "opencode", "unknown"):
            for raw in ("{", "", "[]", "{}" + " " * dispatch.MAX_STDIN):
                with self.subTest(harness=harness, raw=raw[:20]):
                    code, out, err = self.invoke(raw, harness)
                    self.assertEqual(2, code)
                    self.assertEqual("", out)
                    self.assertIn("hook stdin", err)
                    self.assertIn("blocked", err)

    def test_metadata_read_failure_blocks(self):
        with patch.object(dispatch, "load_meta", side_effect=OSError("missing")):
            code, out, err = self.invoke("{}")
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("hooks.meta.json", err)

    def test_outer_failure_blocks(self):
        with patch.object(dispatch, "active_profile", side_effect=RuntimeError("broken")):
            code, out, err = self.invoke("{}")
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("unexpected dispatcher failure", err)

    def test_outer_failure_blocks_opencode_event_alias(self):
        with patch.object(dispatch, "active_profile", side_effect=RuntimeError("broken")):
            code, out, err = self.invoke("{}", "opencode", "tool.execute.before")
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("unexpected dispatcher failure", err)

    def test_valid_payload_without_modules_allows(self):
        with patch.object(dispatch, "load_meta", return_value={"modules": []}):
            self.assertEqual((0, "", ""), self.invoke("{}"))

    def test_native_and_non_pretool_failures_keep_existing_behavior(self):
        self.assertEqual((0, "", ""), self.invoke("{", "claude"))
        self.assertEqual((0, "", ""), self.invoke("{", event="PostToolUse"))


if __name__ == "__main__":
    unittest.main()
