# Tests for the Neva runtime adapted from affaan-m/ECC (MIT), commit d3b8a3e.
"""Failures inside guard modules must not allow foreign harness actions."""
import os
import types
import unittest
from unittest.mock import patch
from test_hooks import HookTest, dispatch, common


class TestModuleFailures(unittest.TestCase):
    modules = [{"id": "guard", "module": "fake", "function": "run"}]

    def run_guard(self, result=None, failure=False, harness="codex", event="PreToolUse"):
        ctx = common.Ctx(event, "", {}, "standard", harness=harness)
        def run(_):
            if failure:
                raise RuntimeError("guard crashed")
            return result
        with patch.object(dispatch.importlib, "import_module", return_value=types.SimpleNamespace(run=run)), \
             patch.object(common, "log_exception"):
            results = dispatch.run_modules(ctx, self.modules)
        return dispatch.merge(event, results, harness)

    def test_exception_blocks_foreign_pretooluse(self):
        for harness in ("codex", "opencode", "cursor", "gemini", "future"):
            with self.subTest(harness=harness):
                output, error, code = self.run_guard(failure=True, harness=harness)
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertIn("[guard] Guard failed", error)

    def test_malformed_decisions_block(self):
        for result in ("allow", False, [], {"permissionDecision": "allow"}, {"block": True}, {"ask": None}):
            with self.subTest(result=result):
                output, error, code = self.run_guard(result)
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertIn("malformed decision", error)

    def test_valid_allow_and_context_are_negative_controls(self):
        for result in (None, {}, {"context": "checked"}):
            with self.subTest(result=result):
                output, error, code = self.run_guard(result)
                self.assertEqual(0, code)
                self.assertEqual("", error)
                self.assertEqual(bool(result), bool(output))

    def test_claude_and_posttool_failure_keep_existing_behavior(self):
        for harness, event in (("claude", "PreToolUse"), ("codex", "PostToolUse")):
            output, error, code = self.run_guard(failure=True, harness=harness, event=event)
            self.assertEqual(("", "", 0), (output, error, code))


class TestNonGuardFailures(unittest.TestCase):
    """Only modules that can block fail closed; a logger or nudge that crashes is skipped."""

    def run_module(self, module, harness="codex"):
        ctx = common.Ctx("PreToolUse", "", {}, "standard", harness=harness)
        def run(_):
            raise PermissionError("data dir is read-only")
        with patch.object(dispatch.importlib, "import_module", return_value=types.SimpleNamespace(run=run)), \
             patch.object(common, "log_exception") as logged:
            results = dispatch.run_modules(ctx, [module])
        return dispatch.merge("PreToolUse", results, harness), logged

    def test_non_guard_exception_is_logged_and_skipped(self):
        for harness in ("codex", "opencode"):
            with self.subTest(harness=harness):
                (output, error, code), logged = self.run_module(
                    {"id": "observe", "module": "fake", "function": "run", "guard": False}, harness)
                self.assertEqual(("", "", 0), (output, error, code))
                self.assertTrue(logged.called)

    def test_guard_block_names_exception_and_disable_switch(self):
        (output, error, code), _ = self.run_module(
            {"id": "config_protection", "module": "fake", "function": "run", "guard": True})
        self.assertEqual(2, code)
        self.assertIn("PermissionError", error)
        self.assertIn("NEVA_DISABLED_HOOKS=config_protection", error)


class TestGuardRegistry(unittest.TestCase):
    GUARDS = {"no_verify", "safety_careful", "safety_freeze", "commit_quality", "vault_gate",
              "config_protection", "gateguard", "hookify_pre_tool"}

    def test_every_pretooluse_module_declares_guard(self):
        for m in dispatch.load_meta()["modules"]:
            if "PreToolUse" not in m["events"]:
                continue
            with self.subTest(module=m["id"]):
                self.assertIsInstance(m.get("guard"), bool, f"{m['id']} needs \"guard\": true or false")
                self.assertEqual(m["id"] in self.GUARDS, m["guard"])


class TestUnwritableDataDir(HookTest):
    """observe cannot write, yet reads and shell calls on foreign harnesses still run."""

    def setUp(self):
        super().setUp()
        self.ro = os.path.join(self.s.tmp, "ro-data")
        os.makedirs(self.ro)
        os.chmod(self.ro, 0o555)

    def tearDown(self):
        os.chmod(self.ro, 0o755)
        super().tearDown()

    def call(self, harness, name, arguments):
        return self.s.dispatch("PreToolUse", self.base(tool_name=name, tool_input=arguments),
                               NEVA_HARNESS=harness, NEVA_DATA_DIR=self.ro)

    def test_reads_and_commands_still_allowed(self):
        target = self.s.write("work/proj/a.txt", "hello\n")
        for harness, name, args in (
            ("codex", "Read", {"file_path": target}),
            ("codex", "exec_command", {"cmd": "ls"}),
            ("codex", "Bash", {"command": "rm -f bigfile"}),
            ("opencode", "read", {"filePath": target}),
        ):
            with self.subTest(harness=harness, name=name):
                self.assertAllowed(self.call(harness, name, args))

    def test_guard_still_blocks_with_unwritable_data_dir(self):
        self.assertBlocked(self.call("codex", "Bash", {"command": "git commit --no-verify -m x"}), "no-verify")


if __name__ == "__main__":
    unittest.main()
