"""Writing into Claude Code's own settings is announced first and can be turned off.

A hands-free install or upgrade merges NEVA_* keys into ~/.claude/settings.json and registers
plugins by default. Before it writes it must print exactly what it will change, and
--no-claude-settings (NEVA_CLAUDE_SETTINGS=no for install.sh) must leave Claude Code's settings
and plugin registry untouched while the rules still install.
"""
import os
import subprocess
import sys

from neva_cli import core
from neva_cli.tests.harness import Sandbox

ORIGINAL = '{"model": "opus"}\n'


class OptOut(Sandbox):
    def setUp(self):
        super().setUp()
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(ORIGINAL, encoding="utf-8")


class TestPlanIsPrinted(OptOut):
    def test_install_prints_each_settings_change_before_making_it(self):
        code, output = self.install(harness="claude", plugins="core,web", profile="strict")
        self.assertEqual(code, 0, output)
        for key, value in (("NEVA_HOOK_PROFILE", "strict"), ("NEVA_PLUGINS", "core,web")):
            self.assertIn('will set env.' + key + ' = "' + value + '" in ' + str(self.settings), output)
        self.assertIn("--no-claude-settings", output, "the opt-out is not named where it matters")

    def test_dry_run_prints_the_same_plan(self):
        code, output = self.install(harness="claude", dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn("will set env.NEVA_HOOK_PROFILE", output)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), ORIGINAL)


class TestOptOut(OptOut):
    def test_no_claude_settings_leaves_settings_and_registry_alone(self):
        before = self.settings.read_bytes()
        code, output = self.install(harness="claude", no_claude_settings=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.settings.read_bytes(), before, "settings.json changed despite the opt-out")
        self.assertEqual(self.claude_state(), {"marketplaces": [], "plugins": []})
        mutations = [call for call in self.recorded() if call["binary"] == "claude"
                     and "--json" not in call["argv"]]
        self.assertEqual(mutations, [], "the claude CLI changed the plugin registry despite the opt-out")
        self.assertIn("--no-claude-settings", output)
        self.assertTrue(list((self.home / ".claude" / "rules" / "neva" / "common").glob("*.md")))

    def test_doctor_does_not_fail_an_install_that_opted_out(self):
        self.install(harness="claude", no_claude_settings=True)
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertIn("--no-claude-settings", output)

    def test_uninstall_after_the_opt_out_restores_home(self):
        before = self.snapshot_home()
        self.install(harness="claude", no_claude_settings=True)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "after an opted-out install and uninstall:")

    def test_negative_control_without_the_flag_settings_change(self):
        self.install(harness="claude")
        self.assertIn("NEVA_PLUGINS", self.settings.read_text(encoding="utf-8"))


class TestInstallShHandsFree(OptOut):
    def test_neva_claude_settings_no_reaches_the_installer(self):
        (self.binroot / "python3").symlink_to(sys.executable)
        env = dict(os.environ, NEVA_NONINTERACTIVE="1", NEVA_SKIP_SCHEDULE_ENABLE="1",
                   OWNER_NAME="Test Owner", VAULT_PATH=str(self.home / "Vault"),
                   WORKSPACE_PATH=str(self.home / "ws"), NEVA_CLAUDE_SETTINGS="no",
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("NEVA_DATA_DIR", None)
        result = subprocess.run(["bash", str(core.REPO_ROOT / "install.sh")], env=env,
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), ORIGINAL,
                         "hands-free install.sh changed Claude settings despite NEVA_CLAUDE_SETTINGS=no")
        self.assertEqual(self.claude_state(), {"marketplaces": [], "plugins": []})
        self.assertIn("NEVA_CLAUDE_SETTINGS", output)


if __name__ == "__main__":
    import unittest
    unittest.main()
