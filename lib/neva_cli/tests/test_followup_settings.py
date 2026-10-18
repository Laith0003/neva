"""Regression checks for installer shell input and remembered Claude consent."""
import os
import subprocess
from neva_cli.tests.test_installed_prefix import InstalledPrefix
from neva_cli import core

class TestSettingsChoice(InstalledPrefix):
    def test_opt_out_is_remembered_by_installed_rerun(self):
        code, output = self.run_neva("install", "--harness", "claude", "--yes", "--no-claude-settings")
        self.assertEqual(code, 0, output)
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("left unchanged", output)
        self.assertFalse((self.home / ".claude/settings.json").exists())
        self.assertEqual(self.recorded(), [])

    def test_shell_invalid_choice_stops_before_writes(self):
        env = dict(os.environ, NEVA_CLAUDE_SETTINGS="never", NEVA_NONINTERACTIVE="1")
        result = subprocess.run(["bash", str(core.REPO_ROOT / "install.sh")], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 64, result.stdout + result.stderr)
        self.assertIn("NEVA_CLAUDE_SETTINGS", result.stderr)
        self.assertIn("yes or no", result.stderr)
        self.assertFalse((self.home / ".config/neva").exists())

    def test_shell_yes_no_variants_and_actual_settings_path(self):
        text = (core.REPO_ROOT / "install.sh").read_text()
        choice = text[text.index('SETTINGS_FLAG=""'):text.index('say()  {')]
        for value, flag in (("n", "--no-claude-settings"), ("No ", "--no-claude-settings"),
                            (" OFF ", "--no-claude-settings"), (" Yes ", "--claude-settings")):
            with self.subTest(value=value):
                result = subprocess.run(["bash", "-c", choice + '\nprintf "%s" "$SETTINGS_FLAG"'],
                                        env=dict(os.environ, NEVA_CLAUDE_SETTINGS=value),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, flag)

    def test_explicit_yes_can_override_remembered_opt_out(self):
        code, output = self.run_neva("install", "--yes", "--no-claude-settings")
        self.assertEqual(code, 0, output)
        code, output = self.run_neva("install", "--yes", "--claude-settings")
        self.assertEqual(code, 0, output)
        self.assertIn("will set env.NEVA_PLUGINS", output)
        self.assertTrue((self.home / ".claude/settings.json").is_file())
        self.assertTrue(self.recorded())

    def test_upgrade_keeps_opt_out_until_explicit_yes(self):
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_bytes(b'{ "model" : "owner" }\n')
        original = settings.read_bytes()
        code, output = self.run_neva("install", "--yes", "--no-claude-settings")
        self.assertEqual(code, 0, output)
        env = dict(os.environ, NEVA_NONINTERACTIVE="1", UPGRADE_CONFIRM="yes",
                   OWNER_NAME="Owner", ENABLE_CADENCE="no", NEVA_SKIP_VAULT_DOCTOR="1")
        env.pop("NEVA_CLAUDE_SETTINGS", None)
        result = subprocess.run(["bash", str(core.REPO_ROOT / "upgrade.sh")], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("left unchanged", result.stdout)
        self.assertEqual(settings.read_bytes(), original)
        self.assertEqual(self.recorded(), [])
        result = subprocess.run(["bash", str(core.REPO_ROOT / "upgrade.sh")],
                                env=dict(env, NEVA_CLAUDE_SETTINGS="yes", CLAUDE_CONFIG_DIR=str(self.home / "other-claude")),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("will set env.NEVA_PLUGINS", result.stdout)
        self.assertIn("env object of " + str(settings), result.stdout)
        self.assertNotIn(str(self.home / "other-claude/settings.json"), result.stdout)
        self.assertNotEqual(settings.read_bytes(), original)
        self.assertTrue(self.recorded())

    def test_fresh_default_writes_settings(self):
        code, output = self.run_neva("install", "--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("will set env.NEVA_PLUGINS", output)
        self.assertTrue((self.home / ".claude/settings.json").is_file())
