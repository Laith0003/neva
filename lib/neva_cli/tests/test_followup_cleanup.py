"""Manifest cleanup regression checks."""
import json
import os

from neva_cli import core
from neva_cli.tests.harness import Sandbox, snapshot
from neva_cli.tests.test_install import SOURCES, adapter


class TestCreatedDirectoryValidation(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", adapter(entries=[adapter()["entries"][0]], post=[]), SOURCES)
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)

    def test_tampered_directory_is_refused_before_files_change(self):
        outside = self.root / "outside"
        outside.mkdir()
        base = self.state()
        for raw in (1, "", "relative", str(self.home / ".." / "outside"), str(outside), str(self.home)):
            with self.subTest(raw=raw):
                state = json.loads(json.dumps(base))
                state["entries"][0]["created_dirs"] = [raw]
                core.save_state(state)
                before = self.snapshot_home()
                manifest = core.state_path().read_bytes()
                code, output = self.uninstall()
                self.assertEqual(code, 1, output)
                self.assertIn("created_dirs", output)
                self.assertIn("fix:", output)
                self.assertHomeUnchanged(before)
                self.assertEqual(core.state_path().read_bytes(), manifest)
                self.assertTrue(outside.is_dir())

    def test_a_recorded_directory_behind_a_symlink_is_skipped_not_removed(self):
        inside = self.home / "empty"
        (inside / "sub").mkdir(parents=True)
        link = self.home / "linked"
        link.symlink_to(inside, target_is_directory=True)
        state = self.state()
        state["entries"][0]["created_dirs"] = state["entries"][0]["created_dirs"] + [str(link), str(link / "sub")]
        core.save_state(state)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertTrue(link.is_symlink(), "uninstall removed a symlink it did not create")
        self.assertTrue((inside / "sub").is_dir(), "uninstall removed a directory through a symlink")
        self.assertFalse((self.home / ".codex").exists())

    def test_prune_refuses_traversal_and_skips_symlinked_or_escaping_paths(self):
        outside = self.root / "outside"
        outside.mkdir()
        child = outside / "child"
        child.mkdir()
        link = self.home / "linked"
        link.symlink_to(outside, target_is_directory=True)
        for raw in (str(self.home / ".." / "outside" / "child"), 1):
            with self.subTest(raw=raw):
                with self.assertRaises(core.ConfigError):
                    core.prune_created([raw])
                self.assertTrue(child.is_dir())
        core.prune_created([str(link / "child"), str(link)])
        self.assertTrue(child.is_dir(), "prune removed a directory outside HOME through a symlink")
        self.assertTrue(link.is_symlink())

    def test_valid_created_directories_are_removed(self):
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertIn("removed", output)
        self.assertFalse((self.home / ".codex").exists())


class TestSymlinkedDirectoriesStillLoad(Sandbox):
    """A symlink the owner put in place later is not a corrupt manifest."""

    def test_a_created_directory_moved_into_dotfiles_still_allows_doctor_and_repair(self):
        self.write_adapter("codex", adapter(), SOURCES)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        rules = self.home / ".claude" / "rules"
        self.assertIn(str(rules.resolve()), [directory for entry in self.entries("claude")
                                             for directory in entry.get("created_dirs", [])])
        moved = self.home / "dotfiles" / "rules"
        moved.parent.mkdir()
        os.rename(rules, moved)
        rules.symlink_to(moved, target_is_directory=True)
        self.assertTrue(self.entries("claude"), "load_state refused the manifest")
        code, output = self.doctor(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertNotIn("created_dirs", output)
        before = snapshot(moved)
        code, output = self.repair(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertEqual(snapshot(moved), before, "repair changed files behind the owner's link")


class TestMainEraManifest(Sandbox):
    """Manifests written before directories were resolved record HOME as the owner spelled it."""

    def setUp(self):
        super().setUp()
        real = self.root / "real"
        (real / "home").mkdir(parents=True)
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        self.home = alias / "home"
        self.env({"HOME": str(self.home)})
        self.write_adapter("codex", adapter(post=[]), SOURCES)

    def test_unresolved_paths_under_a_symlinked_home_ancestor_load_doctor_and_uninstall(self):
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        resolved, spelled = str(self.home.resolve()), str(self.home)
        self.assertNotEqual(resolved, spelled)
        state = json.loads(core.state_path().read_text(encoding="utf-8"))
        for entry in state["entries"]:
            entry["created_dirs"] = [spelled + raw[len(resolved):] if raw.startswith(resolved + os.sep) else raw
                                     for raw in entry.get("created_dirs", [])]
        recorded = [raw for entry in state["entries"] for raw in entry.get("created_dirs", [])]
        self.assertTrue(recorded and all(raw.startswith(spelled + os.sep) for raw in recorded), recorded)
        core.save_state(state)
        self.assertTrue(self.entries("codex"), "load_state refused a main-era manifest")
        code, output = self.doctor(harness="codex")
        self.assertEqual(code, 0, output)
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before, "a main-era manifest did not uninstall cleanly:")


class TestRenamedHome(Sandbox):
    def test_manifest_from_old_home_names_old_and_current_home_without_changes(self):
        self.write_adapter("codex", adapter(post=[]), SOURCES)
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        old = self.home
        new = self.root / "renamed-home"
        os.rename(old, new)
        self.home = new
        self.env({"HOME": str(new)})
        manifest = core.state_path().read_bytes()
        before = self.snapshot_home()
        for command in (self.repair, self.uninstall):
            code, output = command(harness="codex")
            self.assertEqual(code, 1, output)
            self.assertIn("the manifest was written for HOME " + str(old) +
                          "; neva cannot act on it from " + str(new), output)
            self.assertEqual(core.state_path().read_bytes(), manifest)
            self.assertHomeUnchanged(before)

    def test_one_foreign_path_is_not_misreported_as_a_renamed_home(self):
        self.write_adapter("codex", adapter(post=[]), SOURCES)
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        state = self.state()
        state["entries"][0]["created_dirs"] = [str(self.root / "other-home" / ".codex")]
        core.save_state(state)
        before = self.snapshot_home()
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("created_dirs", output)
        self.assertNotIn("manifest was written for HOME", output)
        self.assertHomeUnchanged(before)
