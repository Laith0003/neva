# Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva.
"""The round trip that matters: install, doctor green, tamper, doctor red, repair, uninstall.

The last step is the strict one. After uninstall, everything in HOME outside Neva's own data
directory must be byte for byte what it was before install: same files, same bytes, same
modes, same symlink targets, no leftover empty directories. The backups Neva took are
deliberately kept, so the data directory is excluded and asserted separately.
"""
import json
import os
import unittest
import unittest.mock
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox, difference
from neva_cli.tests.test_install import SOURCES, adapter


class Lifecycle(Sandbox):
    """A sandbox with a fixture adapter and some pre-existing user content to protect."""

    def setUp(self):
        super().setUp()
        self.write_adapter("codex", adapter(), SOURCES)
        # Files the user owns. Uninstall has to hand every one of these back untouched.
        (self.home / ".claude").mkdir(parents=True)
        # No env object: Neva creates one, so uninstall has to take the container away again.
        (self.home / ".claude" / "settings.json").write_text(
            '{\n  "model": "opus"\n}\n', encoding="utf-8")
        (self.home / ".codex" / "prompts").mkdir(parents=True)
        # Destinations the user already filled: a copy target, a symlink target, and the three
        # shared files below. Uninstall has to put every one of them back from its backup.
        (self.home / ".codex" / "AGENTS.md").write_text(
            "the user wrote their own agent instructions here\n", encoding="utf-8")
        (self.home / ".codex" / "prompts" / "neva.md").write_text(
            "a real file where Neva wants a symlink\n", encoding="utf-8")
        # neva.profile is already set here, so install overwrites a value rather than adding one
        # and uninstall has to hand the old value back, not delete the key.
        (self.home / ".codex" / "settings.json").write_text(
            '{"editor": "vim", "neva": {"other": 1, "profile": "the user chose this"}}',
            encoding="utf-8")
        (self.home / ".codex" / "config.toml").write_text(
            '# the user wrote this\nmodel = "gpt"\n\n[tool.other]\nkeep = true\n', encoding="utf-8")
        (self.home / ".profile").write_text('export EDITOR=vim\n', encoding="utf-8")
        self.before = self.snapshot_home()


class TestRoundTrip(Lifecycle):
    def test_install_doctor_tamper_repair_uninstall(self):
        code, output = self.install(harness="all", plugins="core,web")
        self.assertEqual(code, 0, output)

        code, output = self.doctor()
        self.assertEqual(code, 0, "doctor was not green after a clean install:\n" + output)
        self.assertNotIn("FAIL", output)

        rule = next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy")
        Path(rule).write_text("someone edited this rule by hand\n", encoding="utf-8")
        code, output = self.doctor()
        self.assertEqual(code, 1, "doctor stayed green over a modified rule:\n" + output)
        self.assertIn("entry modified: " + rule, output)
        self.assertIn("fix: run neva repair --harness claude", output)

        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertIn("repaired " + rule, output)
        self.assertIn("(modified)", output)

        code, output = self.doctor()
        self.assertEqual(code, 0, "doctor did not go green again after repair:\n" + output)

        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(self.before, "after uninstall:")

    def test_a_deleted_file_is_also_repaired(self):
        self.install(harness="codex")
        target = self.home / ".codex" / "AGENTS.md"
        target.unlink()
        code, output = self.doctor(harness="codex")
        self.assertEqual(code, 1)
        self.assertIn("entry missing: " + str(target), output)
        _, output = self.repair(harness="codex")
        self.assertIn("(missing)", output)
        self.assertEqual(target.read_text(encoding="utf-8"), SOURCES["AGENTS.md"])
        self.assertEqual(self.doctor(harness="codex")[0], 0)

    def test_a_broken_symlink_is_repaired(self):
        self.install(harness="codex")
        link = self.home / ".codex" / "prompts" / "neva.md"
        link.unlink()
        link.symlink_to("/home/user/somewhere-else")
        self.assertEqual(self.doctor(harness="codex")[0], 1)
        self.repair(harness="codex")
        self.assertEqual(self.doctor(harness="codex")[0], 0)
        self.assertTrue(link.is_symlink())

    def test_repair_leaves_files_neva_does_not_own_alone(self):
        self.install(harness="codex")
        stranger = self.home / ".codex" / "not-ours.md"
        stranger.write_text("whatever the user likes\n", encoding="utf-8")
        _, output = self.repair()
        self.assertIn("nothing to repair", output)
        self.assertEqual(stranger.read_text(encoding="utf-8"), "whatever the user likes\n")


class TestUninstallPrecision(Lifecycle):
    def test_shared_json_keeps_the_users_keys_and_comes_back_byte_identical(self):
        settings = self.home / ".claude" / "settings.json"
        settings.write_text('{\n  "model": "opus",\n  "env": {\n    "MY_OWN": "keep"\n  }\n}\n',
                            encoding="utf-8")
        original = settings.read_bytes()
        self.install(harness="claude")
        merged = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(merged["env"]["MY_OWN"], "keep")
        self.uninstall(harness="claude")
        self.assertEqual(settings.read_bytes(), original,
                         "settings.json did not come back byte for byte")

    def test_an_env_object_neva_created_is_taken_away_again(self):
        settings = self.home / ".claude" / "settings.json"
        self.assertNotIn("env", json.loads(settings.read_text(encoding="utf-8")))
        self.install(harness="claude")
        self.assertIn("env", json.loads(settings.read_text(encoding="utf-8")))
        self.uninstall(harness="claude")
        after = json.loads(settings.read_text(encoding="utf-8"))
        self.assertNotIn("env", after, "an empty env object Neva created was left behind")
        self.assertEqual(after["model"], "opus")

    def test_an_overwritten_key_gets_the_users_old_value_back(self):
        settings = self.home / ".codex" / "settings.json"
        self.install(harness="codex")
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["neva"]["profile"],
                         "standard")
        entry = next(item for item in self.entries("codex") if item.get("key") == "neva.profile")
        self.assertEqual(entry["previous"], {"present": True, "value": "the user chose this"})
        self.uninstall(harness="codex")
        after = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(after["neva"]["profile"], "the user chose this",
                         "uninstall deleted a key it had only overwritten")
        self.assertEqual(after["neva"]["other"], 1)

    def test_a_replaced_file_comes_back_from_its_backup(self):
        target = self.home / ".codex" / "AGENTS.md"
        original = target.read_bytes()
        self.install(harness="codex")
        self.assertEqual(target.read_text(encoding="utf-8"), SOURCES["AGENTS.md"])
        self.uninstall(harness="codex")
        self.assertEqual(target.read_bytes(), original,
                         "a file Neva replaced was not restored from its backup")

    def test_a_file_replaced_by_a_symlink_comes_back_as_a_file(self):
        target = self.home / ".codex" / "prompts" / "neva.md"
        original = target.read_bytes()
        self.install(harness="codex")
        self.assertTrue(target.is_symlink())
        self.uninstall(harness="codex")
        self.assertFalse(target.is_symlink(), "a user file was left as a Neva symlink")
        self.assertEqual(target.read_bytes(), original)

    def test_a_file_neva_created_is_deleted_and_its_directory_pruned(self):
        rules = self.home / ".claude" / "rules"
        self.assertFalse(rules.exists())
        self.install(harness="claude")
        self.assertTrue((rules / "neva" / "common").is_dir())
        self.uninstall(harness="claude")
        self.assertFalse(rules.exists(), "an empty rules tree Neva created was left behind")

    def test_a_merged_toml_keeps_the_users_tables(self):
        config = self.home / ".codex" / "config.toml"
        self.install(harness="codex")
        after = core.read_toml(config)
        self.assertEqual(after["model"], "gpt")
        self.assertEqual(after["tool"]["other"], {"keep": True})
        self.assertEqual(after["tool"]["neva"]["profile"], "standard")
        self.uninstall(harness="codex")
        back = core.read_toml(config)
        self.assertNotIn("neva", back["tool"])
        self.assertEqual(back["tool"]["other"], {"keep": True})
        self.assertEqual(back["model"], "gpt")

    def test_an_appended_block_is_removed_without_touching_the_rest(self):
        profile = self.home / ".profile"
        original = profile.read_bytes()
        self.install(harness="codex")
        self.assertIn("# neva begin codex", profile.read_text(encoding="utf-8"))
        self.uninstall(harness="codex")
        self.assertEqual(profile.read_bytes(), original)

    def test_a_block_appended_to_a_file_without_a_trailing_newline_still_undoes_exactly(self):
        profile = self.home / ".profile"
        profile.write_text("export EDITOR=vim", encoding="utf-8")  # no trailing newline
        original = profile.read_bytes()
        self.install(harness="codex")
        self.uninstall(harness="codex")
        self.assertEqual(profile.read_bytes(), original)

    def test_a_users_later_edit_to_a_shared_file_survives_uninstall(self):
        settings = self.home / ".claude" / "settings.json"
        self.install(harness="claude")
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["env"]["ADDED_LATER"] = "mine"
        settings.write_text(json.dumps(data), encoding="utf-8")
        self.uninstall(harness="claude")
        after = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(after["env"]["ADDED_LATER"], "mine",
                         "uninstall discarded an edit the user made after install")
        self.assertEqual(after["model"], "opus")
        self.assertNotIn("NEVA_PLUGINS", after["env"])

    def test_harness_scoped_uninstall_leaves_the_other_harness_installed(self):
        self.install(harness="all")
        self.uninstall(harness="codex")
        state = core.load_state()
        self.assertNotIn("codex", state["harnesses"])
        self.assertIn("claude", state["harnesses"])
        self.assertTrue((self.home / ".claude" / "rules" / "neva" / "common").is_dir())

    def test_the_manifest_is_removed_once_it_owns_nothing(self):
        self.install(harness="codex")
        self.assertTrue(core.state_path().is_file())
        self.uninstall()
        self.assertFalse(core.state_path().exists())

    def test_backups_are_kept_after_uninstall(self):
        self.install(harness="codex")
        self.uninstall()
        self.assertTrue(list((self.data / "backups").glob("*/*")),
                        "uninstall deleted the backups it took")

    def test_with_the_default_data_dir_only_the_backups_remain_under_home(self):
        # The strict byte-identity test above moves NEVA_DATA_DIR out of HOME. This one runs
        # the real default, ~/.local/share/neva, and pins what is allowed to survive there.
        os.environ.pop("NEVA_DATA_DIR")
        default = self.home / ".local" / "share" / "neva"
        self.assertEqual(core.data_dir(), default)
        self.install(harness="codex")
        self.assertTrue((default / "install-state.json").is_file())
        self.uninstall()
        self.assertFalse((default / "install-state.json").exists())
        survivors = sorted(path.name for path in default.iterdir())
        self.assertEqual(survivors, ["backups"],
                         "something other than the backups was left in the data directory")
        self.assertEqual(difference(self.before, self.snapshot_home()),
                         ["added .local", "added .local/share", "added .local/share/neva",
                          "added .local/share/neva/backups"] +
                         sorted("added " + str(path.relative_to(self.home))
                                for path in sorted(default.glob("backups/**/*"))),
                         "uninstall left more under HOME than the backups it is keeping")

    def test_a_non_interactive_uninstall_without_yes_removes_nothing(self):
        self.install(harness="codex")
        after_install = self.snapshot_home()
        code, output = self.uninstall(yes=False)
        self.assertEqual(code, 64)
        self.assertIn("--yes", output)
        self.assertEqual(difference(after_install, self.snapshot_home()), [])

    def test_uninstall_dry_run_removes_nothing(self):
        self.install(harness="codex")
        after_install = self.snapshot_home()
        code, output = self.uninstall(dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("would remove", output)
        self.assertEqual(difference(after_install, self.snapshot_home()), [])
        self.assertTrue(core.state_path().is_file())


class TestEditedManagedFiles(Lifecycle):
    """Uninstall checks a Neva-owned file against its checksum before deleting or overwriting it."""

    def test_an_edited_copy_neva_created_is_kept_and_reported(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        edited = rule.read_text(encoding="utf-8") + "MY EDIT\n"
        rule.write_text(edited, encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn(str(rule), output)
        self.assertIn("edited", output)
        self.assertIn("fix:", output)
        self.assertEqual(rule.read_text(encoding="utf-8"), edited, "uninstall deleted the owner's edit")
        self.assertTrue(any(entry["dest"] == str(rule) for entry in self.entries("claude")))

    def test_an_edited_copy_over_a_user_file_is_not_overwritten_by_the_backup(self):
        target = self.home / ".codex" / "AGENTS.md"
        self.install(harness="codex")
        target.write_text("edited after install\n", encoding="utf-8")
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertEqual(target.read_text(encoding="utf-8"), "edited after install\n")

    def test_a_repointed_neva_symlink_is_kept_and_reported(self):
        link = self.home / ".codex" / "prompts" / "neva.md"
        self.install(harness="codex")
        link.unlink()
        link.symlink_to(self.home / ".profile")
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn(str(link), output)
        self.assertEqual(os.readlink(link), str(self.home / ".profile"))

    def test_once_the_owner_takes_the_edit_away_uninstall_finishes(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        original = rule.read_bytes()
        rule.write_text("MY EDIT\n", encoding="utf-8")
        self.uninstall()
        rule.write_bytes(original)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(self.before, "after the owner reverted the edit:")


class TestOwnersDirectories(Sandbox):
    """Uninstall prunes only directories install created, never one the owner already had."""

    def test_an_empty_directory_the_owner_had_survives(self):
        (self.home / ".claude" / "rules").mkdir(parents=True)
        (self.home / ".codex-empty").mkdir()
        before = self.snapshot_home()
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / ".claude" / "rules").is_dir(),
                        "uninstall removed an empty directory the owner had before install")
        self.assertHomeUnchanged(before, "after uninstall:")

    def test_negative_control_directories_install_created_are_still_pruned(self):
        before = self.snapshot_home()
        self.install(harness="claude")
        self.assertTrue((self.home / ".claude" / "rules" / "neva").is_dir())
        self.uninstall()
        self.assertFalse((self.home / ".claude").exists())
        self.assertHomeUnchanged(before, "after uninstall:")


class TestMissingBackup(Lifecycle):
    """A required backup that is gone is a failure that keeps ownership, never a quiet success."""

    def setUp(self):
        super().setUp()
        self.target = self.home / ".codex" / "AGENTS.md"
        self.original = self.target.read_bytes()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.backup = Path(next(entry["backup"] for entry in self.entries("codex")
                                if entry["dest"] == str(self.target)))
        self.saved_bytes = self.backup.read_bytes()

    def test_a_lost_backup_fails_uninstall_and_keeps_the_entry(self):
        self.backup.unlink()
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn(str(self.backup), output)
        self.assertIn("fix:", output)
        self.assertTrue(core.state_path().is_file(), "the manifest was deleted although an entry failed")
        self.assertTrue(any(entry["dest"] == str(self.target) for entry in self.entries("codex")),
                        "ownership of the replaced file was forgotten")

    def test_putting_the_backup_back_lets_the_next_uninstall_restore_the_original(self):
        self.backup.unlink()
        self.uninstall()
        self.backup.write_bytes(self.saved_bytes)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertHomeUnchanged(self.before, "after the retried uninstall:")

    def test_a_backup_replaced_by_a_directory_is_unusable_and_fails(self):
        self.backup.unlink()
        self.backup.mkdir()
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn(str(self.backup), output)


class TestKeylessMerge(Lifecycle):
    """A merge entry must name its key. Without one it would claim success and apply nothing."""

    def contract(self, mode, key):
        entry = {"src": "settings.json" if mode == "merge-json" else "config.toml",
                 "dest": "~/.keyless/settings.json" if mode == "merge-json" else "~/.keyless/config.toml",
                 "mode": mode}
        if key is not None:
            entry["key"] = key
        return {"harness": "keyless", "entries": [entry]}

    def test_omitted_and_empty_keys_are_refused_for_json_and_toml(self):
        for mode in ("merge-json", "merge-toml"):
            for key in (None, ""):
                with self.subTest(mode=mode, key=key):
                    self.write_adapter("keyless", self.contract(mode, key), {
                        "settings.json": '{"neva": {"profile": "standard"}}',
                        "config.toml": '[neva]\nprofile = "standard"\n'})
                    code, output = self.install(harness="keyless")
                    self.assertEqual(code, 1, output)
                    self.assertIn("key", output)
                    self.assertIn("fix:", output)
                    self.assertNotIn("managed", output)
                    self.assertFalse((self.home / ".keyless").exists(), "a keyless merge wrote a file")
                    self.assertEqual(self.entries("keyless"), [])

    def test_negative_control_a_keyed_merge_installs_and_doctor_is_green(self):
        self.write_adapter("keyless", self.contract("merge-json", "neva.profile"),
                           {"settings.json": '{"neva": {"profile": "standard"}}'})
        code, output = self.install(harness="keyless")
        self.assertEqual(code, 0, output)
        code, output = self.doctor(harness="keyless")
        self.assertEqual(code, 0, output)
        self.uninstall(harness="keyless")
        self.assertHomeUnchanged(self.before)


class TestIncompatibleParents(Lifecycle):
    """A dotted merge never replaces a parent that holds something other than a mapping."""

    def check_parent(self, parent_json):
        settings = self.home / ".codex" / "settings.json"
        original = '{"keep": "mine", "neva": ' + parent_json + '}\n'
        settings.write_text(original, encoding="utf-8")
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("neva.profile", output)
        self.assertIn("fix:", output)
        self.assertEqual(settings.read_text(encoding="utf-8"), original,
                         "install replaced a non-mapping parent")
        self.assertFalse(any(entry.get("key") == "neva.profile" for entry in self.entries("codex")))
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "after uninstall with a " + parent_json + " parent:")

    def test_a_scalar_parent_survives_the_lifecycle(self):
        self.check_parent('"a string the user set"')

    def test_a_list_parent_survives_the_lifecycle(self):
        self.check_parent("[1, 2]")

    def test_a_null_parent_survives_the_lifecycle(self):
        self.check_parent("null")

    def test_a_scalar_toml_parent_is_refused(self):
        config = self.home / ".codex" / "config.toml"
        original = 'model = "gpt"\ntool = 3\n'
        config.write_text(original, encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("tool.neva", output)
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_negative_control_a_mapping_parent_still_merges(self):
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)


class TestNegativeControls(Lifecycle):
    """Each of these proves a check above is capable of failing. Without them it proves nothing."""

    def test_the_byte_identity_comparison_catches_a_file_left_behind(self):
        self.install(harness="codex")
        self.uninstall()
        leaked = self.home / ".codex" / "leftover.md"
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_text("a file uninstall should have removed\n", encoding="utf-8")
        changes = difference(self.before, self.snapshot_home())
        self.assertIn("added .codex/leftover.md", changes)
        with self.assertRaises(AssertionError):
            self.assertHomeUnchanged(self.before)

    def test_the_byte_identity_comparison_catches_changed_bytes(self):
        self.install(harness="codex")
        self.uninstall()
        (self.home / ".profile").write_text("export EDITOR=nano\n", encoding="utf-8")
        self.assertIn("changed .profile", difference(self.before, self.snapshot_home()))

    def test_the_byte_identity_comparison_catches_a_file_turned_into_a_symlink(self):
        self.install(harness="codex")
        self.uninstall()
        profile = self.home / ".profile"
        profile.unlink()
        profile.symlink_to("/home/user/elsewhere")
        self.assertIn("changed .profile", difference(self.before, self.snapshot_home()))

    def test_doctor_cannot_pass_a_tampered_merge_key(self):
        self.install(harness="codex")
        settings = self.home / ".codex" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["neva"]["profile"] = "something else"
        settings.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.doctor(harness="codex")
        self.assertEqual(code, 1, "doctor passed a merge key that was edited:\n" + output)
        self.assertIn("neva.profile", output)

    def test_doctor_cannot_pass_a_tampered_append_block(self):
        self.install(harness="codex")
        profile = self.home / ".profile"
        profile.write_text(profile.read_text(encoding="utf-8").replace("vault", "elsewhere"),
                           encoding="utf-8")
        code, output = self.doctor(harness="codex")
        self.assertEqual(code, 1)
        self.assertIn(".profile", output)

    def test_doctor_reports_a_harness_that_was_never_installed(self):
        self.install(harness="codex")
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("claude is not installed", output)
        self.assertIn("fix: run neva install --harness claude --yes", output)

    def test_doctor_with_no_install_state_at_all_fails_and_names_the_fix(self):
        code, output = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("no harness install state", output)
        self.assertIn("fix: run neva install", output)


class TestDoctorVaultHalf(Lifecycle):
    """doctor's first half shells out to bin/doctor. These pin that it really does."""

    def test_the_vault_half_runs_and_its_output_is_shown(self):
        self.install(harness="codex")
        stub = self.root / "fake-repo"
        (stub / "bin").mkdir(parents=True)
        script = stub / "bin" / "doctor"
        script.write_text("#!/bin/sh\necho 'ok    vault looks fine'\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            code, output = self.doctor(harness="codex", no_vault=False)
        self.assertEqual(code, 0)
        self.assertIn("vault looks fine", output)
        self.assertIn("vault doctor clean", output)

    def test_a_failing_vault_doctor_fails_the_whole_run(self):
        self.install(harness="codex")
        stub = self.root / "fake-repo"
        (stub / "bin").mkdir(parents=True)
        script = stub / "bin" / "doctor"
        script.write_text("#!/bin/sh\necho 'FAIL  vault is broken'\nexit 1\n", encoding="utf-8")
        script.chmod(0o755)
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            code, output = self.doctor(harness="codex", no_vault=False)
        self.assertEqual(code, 1, "a failing bin/doctor did not fail neva doctor")
        self.assertIn("vault doctor reported failures", output)

    def test_a_missing_bin_doctor_is_a_named_failure_not_a_silent_pass(self):
        self.install(harness="codex")
        with unittest.mock.patch.object(core, "REPO_ROOT", self.root / "nowhere"):
            code, output = self.doctor(harness="codex", no_vault=False)
        self.assertEqual(code, 1)
        self.assertIn("vault doctor missing at", output)
        self.assertIn("fix: restore bin/doctor", output)

    def test_the_skip_variable_skips_without_pretending_it_passed(self):
        self.install(harness="codex")
        self.env({"NEVA_SKIP_VAULT_DOCTOR": "1"})
        code, output = self.doctor(harness="codex", no_vault=False)
        self.assertEqual(code, 0)
        self.assertIn("SKIP", output)
        self.assertNotIn("vault doctor clean", output)


class TestDoctorHarnessChecks(Lifecycle):
    def test_a_missing_claude_binary_fails_the_nightly_job_check(self):
        self.install(harness="claude")
        self.hide("claude")
        os.environ.pop("NEVA_CLAUDE_BIN", None)
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("nightly Claude command missing", output)
        self.assertIn("NEVA_CLAUDE_BIN", output)

    def test_neva_claude_bin_satisfies_the_nightly_job_check_without_a_path_entry(self):
        self.install(harness="claude")
        binary = str(self.binroot / "claude")
        self.hide("claude")
        (self.root / "claude-elsewhere").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.env({"NEVA_CLAUDE_BIN": str(self.root / "claude-elsewhere")})
        _, output = self.doctor(harness="claude")
        self.assertIn("nightly Claude command available", output)
        self.assertNotIn("nightly Claude command missing", output)
        self.assertTrue(binary)

    def test_the_hook_dispatcher_and_its_registration_are_checked(self):
        self.install(harness="claude")
        _, output = self.doctor(harness="claude")
        self.assertIn("every hook module's event is registered in hooks.json", output)
        self.assertIn("Claude hook dispatcher runs", output)

    def test_doctor_leaves_user_state_unchanged(self):
        self.install(harness="claude")
        before = self.snapshot_home()
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "doctor wrote to HOME:")

    def test_the_dispatcher_probe_never_sees_the_users_vault_or_state(self):
        self.install(harness="claude")
        stub = self.fake_hooks(["SessionStart"], ["SessionStart"])
        # Exits 5 when it can see the user's HOME or vault, which is exactly what a probe that
        # runs the real hooks must never do: SessionStart hooks write state and read the vault.
        (stub / "plugins" / "neva-core" / "hooks" / "dispatch.py").write_text(
            "import os, sys\n"
            "seen = os.environ.get('HOME') == os.environ['PROBE_REAL_HOME'] or bool(os.environ.get('NEVA_VAULT'))\n"
            "sys.exit(5 if seen else 0)\n", encoding="utf-8")
        self.env({"PROBE_REAL_HOME": str(self.home), "NEVA_VAULT": str(self.home / "vault")})
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, "the dispatcher probe ran against the real HOME or vault:\n" + output)

    def fake_hooks(self, registered, declared):
        """A stub repo whose hooks.json registers `registered` and whose modules want `declared`."""
        stub = self.root / "fake-hooks"
        hooks = stub / "plugins" / "neva-core" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "hooks.json").write_text(
            json.dumps({"hooks": {name: [] for name in registered}}), encoding="utf-8")
        (hooks / "hooks.meta.json").write_text(
            json.dumps({"modules": [{"name": "m", "events": declared}]}), encoding="utf-8")
        (hooks / "dispatch.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        return stub

    def test_a_module_listening_to_an_unregistered_event_is_a_named_failure(self):
        self.install(harness="claude")
        stub = self.fake_hooks(["SessionStart"], ["SessionStart", "PreToolUse"])
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1, "doctor passed a hook event that is never registered")
        self.assertIn("hook events with modules but no registration: PreToolUse", output)
        self.assertIn("fix: add those events to", output)

    def test_negative_control_matching_registration_passes_the_same_check(self):
        self.install(harness="claude")
        stub = self.fake_hooks(["SessionStart", "PreToolUse"], ["SessionStart", "PreToolUse"])
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            _, output = self.doctor(harness="claude")
        self.assertIn("every hook module's event is registered", output)
        self.assertNotIn("no registration", output)

    def test_a_crashing_dispatcher_is_a_named_failure(self):
        self.install(harness="claude")
        stub = self.fake_hooks(["SessionStart"], ["SessionStart"])
        (stub / "plugins" / "neva-core" / "hooks" / "dispatch.py").write_text(
            "import sys\nsys.exit(3)\n", encoding="utf-8")
        with unittest.mock.patch.object(core, "REPO_ROOT", stub):
            code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("Claude hook dispatcher exited 3", output)

    def test_a_deleted_rule_is_reported_as_a_rule_not_just_as_an_entry(self):
        self.install(harness="claude")
        rule = next(entry["dest"] for entry in self.entries("claude")
                    if "/rules/neva/" in entry["dest"])
        Path(rule).unlink()
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("Claude rules missing, first: " + rule, output)
        self.assertIn("fix: run neva repair --harness claude", output)

    def test_env_missing_from_settings_is_a_named_failure(self):
        self.install(harness="claude")
        settings = self.home / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["env"].pop("NEVA_PLUGINS")
        settings.write_text(json.dumps(data), encoding="utf-8")
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 1)
        self.assertIn("NEVA_PLUGINS", output)

    def test_an_unregistered_marketplace_warns_but_does_not_fail(self):
        # Installed while claude was off PATH, so nothing was registered or recorded.
        self.hide("claude")
        self.install(harness="claude")
        self.stateful_claude()
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0)
        self.assertIn("marketplace is not registered", output)
        self.assertIn("fix: run claude plugin marketplace add", output)

    def test_a_registered_marketplace_is_reported_as_ok(self):
        self.hide("claude")
        self.install(harness="claude")
        self.stateful_claude()
        self.seed_claude([{"name": "neva", "source": "/home/user/neva"}])
        _, output = self.doctor(harness="claude")
        self.assertIn("marketplace is registered", output)


if __name__ == "__main__":
    unittest.main()
