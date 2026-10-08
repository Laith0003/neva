"""A configuration file Neva cannot parse is refused by name and left byte for byte alone.

Missing is not the same as broken. A missing settings file is an empty mapping; a file that
holds invalid JSON, or valid JSON whose top level is not an object, is the user's content in a
state Neva does not understand, and overwriting it with only Neva's keys would discard it.
"""
import json
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_install import SOURCES, adapter

BROKEN = '{\n  "model": "opus",\n  "env": {"MINE": "keep"\n'
ARRAY = '[1, 2, 3]\n'


class Malformed(Sandbox):
    def setUp(self):
        super().setUp()
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True)

    def assertRefused(self, code, output, path, reason):
        self.assertEqual(code, 1, output)
        self.assertIn(str(path), output, "the error does not name the file")
        self.assertIn(reason, output)
        self.assertIn("fix:", output)


class TestInstallRefuses(Malformed):
    def test_invalid_claude_settings_are_refused_and_preserved(self):
        self.settings.write_text(BROKEN, encoding="utf-8")
        code, output = self.install(harness="claude")
        self.assertRefused(code, output, self.settings, "not valid JSON")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), BROKEN,
                         "an invalid settings.json was overwritten")

    def test_invalid_claude_settings_stop_the_install_before_any_write(self):
        self.settings.write_text(BROKEN, encoding="utf-8")
        self.install(harness="claude")
        self.assertFalse((self.home / ".claude" / "rules").exists(),
                         "rules were written before the settings were found to be invalid")
        self.assertEqual([call for call in self.recorded() if call["binary"] == "claude"], [],
                         "the claude CLI ran although the install was refused")

    def test_an_array_claude_settings_is_refused_and_preserved(self):
        self.settings.write_text(ARRAY, encoding="utf-8")
        code, output = self.install(harness="claude")
        self.assertRefused(code, output, self.settings, "must hold a JSON object")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), ARRAY)

    def test_an_adapter_destination_holding_an_array_is_refused_and_preserved(self):
        self.write_adapter("codex", adapter(), SOURCES)
        target = self.home / ".codex" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text(ARRAY, encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertRefused(code, output, target, "must hold a JSON object")
        self.assertEqual(target.read_text(encoding="utf-8"), ARRAY,
                         "an adapter JSON array was replaced by a mapping")

    def test_an_invalid_adapter_source_is_named(self):
        self.write_adapter("codex", adapter(), dict(SOURCES, **{"settings.json": "{oops"}))
        code, output = self.install(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("settings.json", output)
        self.assertIn("not valid JSON", output)
        self.assertNotIn("source key missing", output, "a parse error was reported as a missing key")

    def test_negative_control_a_missing_settings_file_is_still_created(self):
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertIn("NEVA_PLUGINS", self.settings.read_text(encoding="utf-8"))

    def test_negative_control_an_empty_settings_file_is_treated_as_empty(self):
        self.settings.write_text("", encoding="utf-8")
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)


class TestRepairAndUninstallRefuse(Malformed):
    def setUp(self):
        super().setUp()
        self.settings.write_text('{"model": "opus"}\n', encoding="utf-8")
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)

    def test_repair_leaves_an_invalid_settings_file_alone(self):
        self.settings.write_text(BROKEN, encoding="utf-8")
        code, output = self.repair()
        self.assertRefused(code, output, self.settings, "not valid JSON")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), BROKEN)

    def test_repair_leaves_an_array_settings_file_alone(self):
        self.settings.write_text(ARRAY, encoding="utf-8")
        code, output = self.repair()
        self.assertRefused(code, output, self.settings, "must hold a JSON object")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), ARRAY)

    def test_uninstall_leaves_an_invalid_settings_file_alone_and_keeps_the_entry(self):
        self.settings.write_text(BROKEN, encoding="utf-8")
        code, output = self.uninstall()
        self.assertRefused(code, output, self.settings, "not valid JSON")
        self.assertNotIn("restore write permission", output, "a parse error got a permission fix")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), BROKEN)
        self.assertTrue(any(entry["dest"] == str(self.settings) for entry in self.entries()),
                        "the refused settings entry was dropped, so it can never be retried")

    def test_uninstall_leaves_an_array_settings_file_alone(self):
        self.settings.write_text(ARRAY, encoding="utf-8")
        code, output = self.uninstall()
        self.assertRefused(code, output, self.settings, "must hold a JSON object")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), ARRAY)

    def test_doctor_names_the_parse_error_instead_of_a_missing_key(self):
        self.settings.write_text(BROKEN, encoding="utf-8")
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", output)


class TestCorruptManifest(Sandbox):
    """The install-state manifest is the only record of what to undo. Never treat it as empty."""

    def run_bin(self, *args):
        import subprocess
        import sys
        bin_neva = core.REPO_ROOT / "bin" / "neva"
        result = subprocess.run([sys.executable, str(bin_neva)] + list(args), capture_output=True,
                                text=True, timeout=120, env=dict(__import__("os").environ))
        return result.returncode, result.stdout + result.stderr

    def test_a_corrupt_manifest_stops_every_command_and_is_left_alone(self):
        self.install(harness="claude")
        path = core.state_path()
        path.write_text('{"schema": 1, "entries": [', encoding="utf-8")
        original = path.read_bytes()
        for args in (["install", "--harness", "claude", "--yes"], ["uninstall", "--yes"],
                     ["repair"], ["doctor", "--no-vault"], ["list"]):
            with self.subTest(args=args):
                code, output = self.run_bin(*args)
                self.assertEqual(code, 1, output)
                self.assertIn(str(path), output)
                self.assertIn("fix:", output)
                self.assertNotIn("Traceback", output)
                self.assertEqual(path.read_bytes(), original, "the manifest was overwritten")

    def test_negative_control_a_missing_manifest_is_still_an_empty_one(self):
        self.assertEqual(core.load_state(), core.empty_state())


GOOD_ENTRY = {"harness": "claude", "kind": "copy", "dest": "/home/user/.claude/rules/neva/x.md",
              "source": "/home/user/neva/x.md", "existed": False, "backup": None, "checksum": "ab"}

#: (label, manifest text, field the error must name). Each is valid JSON but not a manifest.
STRUCTURAL = [
    ("blank file", "", "empty"),
    ("empty object", "{}", "schema"),
    ("entries is a string", '{"schema": 1, "harnesses": {}, "entries": "x"}', "entries"),
    ("entries is an object", '{"schema": 1, "harnesses": {}, "entries": {}}', "entries"),
    ("harnesses is a list", '{"schema": 1, "harnesses": [], "entries": []}', "harnesses"),
    ("entry is a string", '{"schema": 1, "harnesses": {}, "entries": ["x"]}', "entries[0]"),
    ("unknown kind", json.dumps({"schema": 1, "harnesses": {}, "entries": [dict(GOOD_ENTRY, kind="beam")]}),
     "entries[0].kind"),
    ("missing dest", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        {key: value for key, value in GOOD_ENTRY.items() if key != "dest"}]}), "entries[0].dest"),
    ("merge without key", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, kind="merge-json", key="")]}), "entries[0].key"),
    ("links of the wrong type", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, links="x")]}), "entries[0].links"),
    ("backup of the wrong type", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, backup=3)]}), "entries[0].backup"),
    ("replaced file without a backup field", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        {key: value for key, value in dict(GOOD_ENTRY, existed=True).items() if key != "backup"}]}),
     "entries[0].backup"),
    ("replaced file with a null backup", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, existed=True, backup=None)]}), "entries[0].backup"),
    ("file entry without existed", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        {key: value for key, value in GOOD_ENTRY.items() if key != "existed"}]}), "entries[0].existed"),
    ("merge without previous", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, kind="merge-json", key="env.X", source=None)]}), "entries[0].previous"),
    ("previous present without a value", json.dumps({"schema": 1, "harnesses": {}, "entries": [
        dict(GOOD_ENTRY, kind="merge-json", key="env.X", source=None, previous={"present": True})]}),
     "entries[0].previous.value"),
]


class TestStructurallyCorruptManifest(Sandbox):
    """Valid JSON that is not a valid manifest is refused by field, never read as no ownership."""

    def test_every_command_refuses_every_structural_corruption(self):
        commands = (("install", lambda: self.install(harness="claude")), ("uninstall", self.uninstall),
                    ("repair", self.repair), ("doctor", self.doctor), ("list", self.list))
        path = core.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        for label, text, field in STRUCTURAL:
            path.write_text(text, encoding="utf-8")
            for name, command in commands:
                with self.subTest(case=label, command=name):
                    code, output = command()
                    self.assertEqual(code, 1, output)
                    self.assertIn(str(path), output)
                    self.assertIn(field, output)
                    self.assertIn("fix:", output)
                    self.assertEqual(path.read_text(encoding="utf-8"), text, "the manifest was rewritten")
        self.assertFalse((self.home / ".claude").exists(), "a command wrote into HOME over a bad manifest")

    def test_a_dropped_backup_field_never_turns_uninstall_into_a_delete(self):
        from neva_cli.tests.test_install import SOURCES, adapter
        self.write_adapter("codex", adapter(), SOURCES)
        target = self.home / ".codex" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("the owner's own file\n", encoding="utf-8")
        self.install(harness="codex")
        path = core.state_path()
        state = json.loads(path.read_text(encoding="utf-8"))
        for entry in state["entries"]:
            if entry["dest"] == str(target):
                del entry["backup"]
        path.write_text(json.dumps(state), encoding="utf-8")
        edited = path.read_bytes()
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn("backup", output)
        self.assertTrue(target.is_file(), "uninstall deleted the file instead of refusing")
        self.assertEqual(path.read_bytes(), edited)

    def test_negative_control_a_well_formed_manifest_loads(self):
        path = core.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "harnesses": {}, "entries": [GOOD_ENTRY]}), encoding="utf-8")
        self.assertEqual(len(core.load_state()["entries"]), 1)


class TestReader(Sandbox):
    def test_missing_is_empty(self):
        self.assertEqual(core.read_json_object(self.home / "absent.json"), {})

    def test_invalid_names_the_line(self):
        path = self.home / "bad.json"
        path.write_text(BROKEN, encoding="utf-8")
        with self.assertRaises(core.ConfigError) as caught:
            core.read_json_object(path)
        self.assertIn("line", str(caught.exception))
        self.assertIn(str(path), str(caught.exception))

    def test_wrong_root_type_names_the_type(self):
        path = self.home / "list.json"
        path.write_text(ARRAY, encoding="utf-8")
        with self.assertRaises(core.ConfigError) as caught:
            core.read_json_object(path)
        self.assertIn("found list", str(caught.exception))

    def test_load_mapping_no_longer_swallows_errors(self):
        path = self.home / "bad.json"
        path.write_text(BROKEN, encoding="utf-8")
        with self.assertRaises(ValueError):
            core.load_mapping(path, "merge-json")
        self.assertEqual(json.loads('{"a": 1}'), core.load_mapping(self._ok(), "merge-json"))

    def _ok(self):
        path = self.home / "ok.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        return Path(path)


if __name__ == "__main__":
    import unittest
    unittest.main()
