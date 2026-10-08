"""Temporary files, the install-state manifest and the backups obey the same path rules.

Round 2 of the review planted symlinks where Neva writes its own bookkeeping: the predictable
settings.json.neva-tmp, the default data directory, the backups directory, the manifest itself
and a single backup file. Each one must be refused or sidestepped, and the outside victim must
come through byte for byte.
"""
import json
import os
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox, snapshot
from neva_cli.tests.test_install import SOURCES, adapter


class Outside(Sandbox):
    def setUp(self):
        super().setUp()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.victim = self.outside / "victim.txt"
        self.victim.write_text("outside content nobody may touch\n", encoding="utf-8")
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('{"model": "opus"}\n', encoding="utf-8")

    def plant_tmp(self, path):
        link = path.with_name(path.name + ".neva-tmp")
        link.symlink_to(self.victim)
        return link

    def assertVictimIntact(self, before, message):
        self.assertEqual(snapshot(self.outside), before, message)


class TestTemporaryFiles(Outside):
    def test_install_does_not_write_through_a_planted_json_temp_link(self):
        self.plant_tmp(self.settings)
        before = snapshot(self.outside)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertVictimIntact(before, "install wrote through settings.json.neva-tmp")
        self.assertIn("NEVA_PLUGINS", self.settings.read_text(encoding="utf-8"))

    def test_repair_does_not_write_through_a_planted_json_temp_link(self):
        self.install(harness="claude")
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        data["env"]["NEVA_PLUGINS"] = "tampered"
        self.settings.write_text(json.dumps(data), encoding="utf-8")
        self.plant_tmp(self.settings)
        before = snapshot(self.outside)
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertVictimIntact(before, "repair wrote through settings.json.neva-tmp")

    def test_uninstall_does_not_write_through_a_planted_json_temp_link(self):
        self.install(harness="claude")
        self.plant_tmp(self.settings)
        before = snapshot(self.outside)
        self.uninstall()
        self.assertVictimIntact(before, "uninstall wrote through settings.json.neva-tmp")

    def test_toml_and_block_writes_do_not_follow_planted_temp_links(self):
        self.write_adapter("codex", adapter(), SOURCES)
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text('model = "gpt"\n', encoding="utf-8")
        profile = self.home / ".profile"
        profile.write_text("export EDITOR=vim\n", encoding="utf-8")
        for path in (config, profile, self.home / ".codex" / "AGENTS.md"):
            self.plant_tmp(path)
        before = snapshot(self.outside)
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.uninstall(harness="codex")
        self.assertVictimIntact(before, "a TOML, block or copy write followed a planted temp link")

    def test_writes_keep_the_mode_of_the_file_they_replace(self):
        self.settings.chmod(0o640)
        self.install(harness="claude")
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o640)


class TestDataDirectory(Outside):
    def use_default_data_dir(self):
        os.environ.pop("NEVA_DATA_DIR")
        return self.home / ".local" / "share" / "neva"

    def test_a_default_data_dir_symlinked_outside_home_is_refused(self):
        default = self.use_default_data_dir()
        default.parent.mkdir(parents=True)
        default.symlink_to(self.outside, target_is_directory=True)
        before = snapshot(self.outside)
        settings_before = self.settings.read_bytes()
        code, output = self.install(harness="claude")
        self.assertEqual(code, 1, output)
        self.assertIn(str(default), output)
        self.assertIn("fix:", output)
        self.assertVictimIntact(before, "install-state or backups were written outside HOME")
        self.assertEqual(self.settings.read_bytes(), settings_before,
                         "install wrote into HOME although it could not record what it wrote")

    def test_a_backups_dir_symlinked_outside_is_refused(self):
        self.data.mkdir(parents=True)
        (self.data / "backups").symlink_to(self.outside, target_is_directory=True)
        before = snapshot(self.outside)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 1, output)
        self.assertIn("backups", output)
        self.assertVictimIntact(before, "a backup was written through a symlinked backups dir")

    def test_a_manifest_replaced_by_a_symlink_is_refused(self):
        self.install(harness="claude")
        state = core.state_path()
        copy = self.outside / "install-state.json"
        copy.write_bytes(state.read_bytes())
        state.unlink()
        state.symlink_to(copy)
        before = snapshot(self.outside)
        for command in (self.install, self.repair, self.uninstall, self.doctor, self.list):
            with self.subTest(command=command.__name__):
                code, output = command()
                self.assertEqual(code, 1, output)
                self.assertIn(str(state), output)
        self.assertVictimIntact(before, "a command wrote through a symlinked manifest")

    def test_a_backup_file_replaced_by_a_symlink_is_not_restored_from(self):
        self.write_adapter("codex", adapter(), SOURCES)
        target = self.home / ".codex" / "AGENTS.md"
        target.parent.mkdir(parents=True)
        target.write_text("the user's own file\n", encoding="utf-8")
        self.install(harness="codex")
        saved = Path(next(entry["backup"] for entry in self.entries("codex")
                          if entry["dest"] == str(target)))
        saved.unlink()
        saved.symlink_to(self.victim)
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn(str(saved), output)
        self.assertNotEqual(target.read_text(encoding="utf-8"), self.victim.read_text(encoding="utf-8"),
                            "uninstall copied an outside file into HOME through a backup symlink")

    def test_negative_control_a_real_default_data_dir_works(self):
        default = self.use_default_data_dir()
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertTrue((default / "install-state.json").is_file())


if __name__ == "__main__":
    import unittest
    unittest.main()
