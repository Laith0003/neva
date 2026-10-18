"""Malformed health-check inputs fail by field without mutating owner files."""
import json
from unittest import mock

from neva_cli import core
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_installed_prefix import InstalledPrefix


class TestDoctorInputShapes(Sandbox):
    def test_non_string_env_values_fail_with_the_field_and_fix(self):
        code, output = self.install()
        self.assertEqual(code, 0, output)
        settings = self.home / ".claude" / "settings.json"
        original = json.loads(settings.read_text())
        for field in ("NEVA_HOOK_PROFILE", "NEVA_PLUGINS"):
            for value in (1, ["core"], {"enabled": True}, False):
                with self.subTest(field=field, value=value):
                    data = json.loads(json.dumps(original))
                    data["env"][field] = value
                    settings.write_text(json.dumps(data))
                    before = self.snapshot_home()
                    code, output = self.doctor(harness="claude")
                    self.assertEqual(code, 1, output)
                    self.assertIn("env." + field, output)
                    self.assertIn("non-empty string", output)
                    self.assertIn("fix:", output)
                    self.assertIn(str(settings), output)
                    self.assertHomeUnchanged(before)

    def test_malformed_hook_metadata_names_its_file_and_field(self):
        code, output = self.install()
        self.assertEqual(code, 0, output)
        fixture = self.root / "hook-fixture"
        hooks = fixture / "plugins" / "neva-core" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "dispatch.py").write_text("raise SystemExit(0)\n")
        (hooks / "hooks.json").write_text('{"hooks": {"SessionStart": []}}')
        cases = [("modules", {"modules": 1}),
                 ("modules[0]", {"modules": [1]}),
                 ("modules[0].events", {"modules": [{"events": "SessionStart"}]}),
                 ("modules[0].events", {"modules": [{"events": [1]}]})]
        for field, metadata in cases:
            with self.subTest(field=field, metadata=metadata):
                (hooks / "hooks.meta.json").write_text(json.dumps(metadata))
                before = self.snapshot_home()
                with mock.patch.object(core, "REPO_ROOT", fixture):
                    code, output = self.doctor(harness="claude")
                self.assertEqual(code, 1, output)
                self.assertIn(str(hooks / "hooks.meta.json"), output)
                self.assertIn(field, output)
                self.assertIn("fix:", output)
                self.assertHomeUnchanged(before)

    def test_control_valid_settings_and_hooks_keep_doctor_green(self):
        code, output = self.install()
        self.assertEqual(code, 0, output)
        before = self.snapshot_home()
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertIn("Claude settings env has", output)
        self.assertIn("every hook module's event is registered", output)
        self.assertHomeUnchanged(before)


class TestInstalledDoctorInputShapes(InstalledPrefix):
    def test_installed_doctor_reports_invalid_env_without_a_traceback(self):
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 0, output)
        settings = self.home / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        data["env"]["NEVA_HOOK_PROFILE"] = 1
        settings.write_text(json.dumps(data))
        before = self.snapshot_home()
        code, output = self.run_neva("doctor", "--no-vault")
        self.assertEqual(code, 1, output)
        self.assertIn("env.NEVA_HOOK_PROFILE must be a non-empty string", output)
        self.assertIn("fix:", output)
        self.assertNotIn("Traceback", output)
        self.assertHomeUnchanged(before)

    def test_invalid_hook_registration_names_its_file(self):
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 0, output)
        registration = self.prefix / "plugins" / "neva-core" / "hooks" / "hooks.json"
        registration.write_text('{"hooks": []}')
        before = self.snapshot_home()
        code, output = self.run_neva("doctor", "--no-vault")
        self.assertEqual(code, 1, output)
        self.assertIn(str(registration) + ": hooks must be an object", output)
        self.assertIn("fix:", output)
        self.assertNotIn("Traceback", output)
        self.assertHomeUnchanged(before)
