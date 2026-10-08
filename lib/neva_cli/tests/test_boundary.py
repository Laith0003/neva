"""The HOME boundary holds for every write, not only for adapter destinations at parse time.

Each test builds the exact escape a reviewer reproduced: a symlink that points out of the
sandbox HOME, planted either before install or after it, under a path Neva manages. The
victim lives outside HOME and must come through byte for byte untouched.
"""
import json
import os
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox, snapshot
from neva_cli.tests.test_install import SOURCES, adapter


class Outside(Sandbox):
    """A sandbox with a directory outside HOME that nothing may write into."""

    def setUp(self):
        super().setUp()
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def assertOutsideUnchanged(self, before, message):
        self.assertEqual(snapshot(self.outside), before, message)


class TestNativeInstallBoundary(Outside):
    def test_a_symlinked_claude_dir_pointing_outside_home_is_refused(self):
        (self.home / ".claude").symlink_to(self.outside, target_is_directory=True)
        before = snapshot(self.outside)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 1, output)
        self.assertIn("outside HOME", output)
        self.assertIn("fix:", output)
        self.assertIn(str(self.home / ".claude"), output, "the error does not name the symlink")
        self.assertFalse((self.outside / "settings.json").exists(), "settings written outside HOME")
        self.assertFalse((self.outside / "rules").exists(), "rules written outside HOME")
        self.assertOutsideUnchanged(before, "native install wrote outside HOME")

    def test_negative_control_a_symlinked_claude_dir_inside_home_installs(self):
        real = self.home / "dotfiles" / "claude"
        real.mkdir(parents=True)
        (self.home / ".claude").symlink_to(real, target_is_directory=True)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        self.assertTrue((real / "rules" / "neva" / "common").is_dir())
        self.assertIn("NEVA_PLUGINS", (real / "settings.json").read_text(encoding="utf-8"))

    def test_dry_run_reports_the_escape_too(self):
        (self.home / ".claude").symlink_to(self.outside, target_is_directory=True)
        code, output = self.install(harness="claude", dry_run=True)
        self.assertEqual(code, 1, output)
        self.assertIn("outside HOME", output)


class TestRepairBoundary(Outside):
    def test_a_managed_copy_replaced_by_an_outside_symlink_is_not_written_through(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        victim = self.outside / "victim.md"
        victim.write_text("the original victim text\n", encoding="utf-8")
        rule.unlink()
        rule.symlink_to(victim)
        before = snapshot(self.outside)
        code, output = self.repair()
        self.assertEqual(code, 1, output)
        self.assertIn("cannot repair " + str(rule), output)
        self.assertIn("outside HOME", output)
        self.assertEqual(victim.read_text(encoding="utf-8"), "the original victim text\n",
                         "repair overwrote a file outside HOME through a symlink")
        self.assertOutsideUnchanged(before, "repair wrote outside HOME")

    def test_a_managed_parent_replaced_by_an_outside_symlink_is_not_written_through(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        parent = rule.parent
        victim_dir = self.outside / "common"
        victim_dir.mkdir()
        (victim_dir / rule.name).write_text("an outside file with the same name\n", encoding="utf-8")
        for child in parent.iterdir():
            child.unlink()
        parent.rmdir()
        parent.symlink_to(victim_dir, target_is_directory=True)
        before = snapshot(self.outside)
        code, output = self.repair()
        self.assertEqual(code, 1, output)
        self.assertIn("outside HOME", output)
        self.assertOutsideUnchanged(before, "repair wrote into an outside directory")

    def test_negative_control_a_modified_copy_inside_home_is_still_repaired(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        rule.write_text("edited\n", encoding="utf-8")
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertIn("repaired " + str(rule), output)

    def test_a_managed_copy_replaced_by_an_inside_symlink_is_refused(self):
        # A link Neva did not create, at a path Neva owns, is a substitution even inside HOME.
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        other = self.home / "notes.md"
        other.write_text("a user file inside HOME\n", encoding="utf-8")
        rule.unlink()
        rule.symlink_to(other)
        code, output = self.repair()
        self.assertEqual(code, 1, output)
        self.assertIn("symlink", output)
        self.assertTrue(rule.is_symlink(), "repair replaced a link it does not own")
        self.assertEqual(other.read_text(encoding="utf-8"), "a user file inside HOME\n")


class TestUninstallBoundary(Outside):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", adapter(), SOURCES)

    def test_a_managed_parent_replaced_by_an_outside_symlink_deletes_nothing_outside(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        parent = rule.parent
        victim_dir = self.outside / "common"
        victim_dir.mkdir()
        (victim_dir / rule.name).write_text("not Neva's file\n", encoding="utf-8")
        for child in parent.iterdir():
            child.unlink()
        parent.rmdir()
        parent.symlink_to(victim_dir, target_is_directory=True)
        before = snapshot(self.outside)
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn("outside HOME", output)
        self.assertTrue((victim_dir / rule.name).is_file(), "uninstall deleted an outside file")
        self.assertOutsideUnchanged(before, "uninstall changed files outside HOME")
        self.assertTrue(any(entry["dest"] == str(rule) for entry in self.entries("claude")),
                        "a refused entry was dropped from the manifest, so it can never be retried")

    def test_an_appended_file_replaced_by_an_outside_symlink_is_not_rewritten(self):
        self.install(harness="codex")
        profile = self.home / ".profile"
        victim = self.outside / "profile"
        victim.write_text(profile.read_text(encoding="utf-8"), encoding="utf-8")
        profile.unlink()
        profile.symlink_to(victim)
        before = snapshot(self.outside)
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertIn("outside HOME", output)
        self.assertOutsideUnchanged(before, "uninstall rewrote a file outside HOME through a symlink")

    def test_a_merged_toml_replaced_by_an_outside_symlink_is_not_rewritten(self):
        self.install(harness="codex")
        config = self.home / ".codex" / "config.toml"
        victim = self.outside / "config.toml"
        victim.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
        config.unlink()
        config.symlink_to(victim)
        before = snapshot(self.outside)
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 1, output)
        self.assertOutsideUnchanged(before, "uninstall rewrote an outside TOML file")

    def test_a_managed_copy_replaced_by_an_outside_symlink_leaves_the_target_alone(self):
        self.install(harness="claude")
        rule = Path(next(entry["dest"] for entry in self.entries("claude") if entry["kind"] == "copy"))
        victim = self.outside / "victim.md"
        victim.write_text("keep me\n", encoding="utf-8")
        rule.unlink()
        rule.symlink_to(victim)
        before = snapshot(self.outside)
        self.uninstall()
        self.assertOutsideUnchanged(before, "uninstall followed a leaf symlink out of HOME")


class TestInsideHomeSubstitution(Outside):
    """Ownership, not just the HOME boundary: a link Neva did not create is never followed."""

    def setUp(self):
        super().setUp()
        self.write_adapter("owned", {
            "harness": "owned",
            "entries": [
                {"src": "item", "dest": "~/owned/item", "mode": "copy"},
                {"src": "link", "dest": "~/owned/link", "mode": "symlink"},
                {"src": "settings.json", "dest": "~/owned/settings.json", "mode": "merge-json",
                 "key": "neva.profile"},
                {"src": "block.sh", "dest": "~/owned/rc", "mode": "append-block", "key": "owned"},
            ]}, {"item": "Neva's item\n", "link": "Neva's link target\n",
                 "settings.json": '{"neva": {"profile": "standard"}}', "block.sh": "export A=1\n"})
        self.user_files = self.home / "user-files"
        self.user_files.mkdir()
        for name, body in (("item", "the user's unrelated item\n"), ("link", "the user's link\n"),
                           ("settings.json", '{"mine": true}\n'), ("rc", "export MINE=1\n")):
            (self.user_files / name).write_text(body, encoding="utf-8")
        code, output = self.install(harness="owned")
        self.assertEqual(code, 0, output)
        self.user_before = snapshot(self.user_files)

    def swap_parent(self):
        owned = self.home / "owned"
        for child in owned.iterdir():
            child.unlink()
        owned.rmdir()
        owned.symlink_to(self.user_files, target_is_directory=True)

    def assertUserFilesIntact(self, message):
        self.assertEqual(snapshot(self.user_files), self.user_before, message)

    def test_uninstall_through_a_parent_swapped_for_an_inside_symlink_deletes_nothing(self):
        self.swap_parent()
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn(str(self.home / "owned"), output)
        self.assertIn("fix:", output)
        self.assertUserFilesIntact("uninstall deleted or rewrote unowned files through a parent link")
        self.assertEqual(len(self.entries("owned")), 4, "refused entries were dropped from the manifest")

    def test_repair_through_a_parent_swapped_for_an_inside_symlink_writes_nothing(self):
        self.swap_parent()
        code, output = self.repair()
        self.assertEqual(code, 1, output)
        self.assertUserFilesIntact("repair wrote through a parent link")

    def test_reinstall_through_a_parent_swapped_for_an_inside_symlink_writes_nothing(self):
        self.swap_parent()
        code, output = self.install(harness="owned")
        self.assertEqual(code, 1, output)
        self.assertUserFilesIntact("a re-install wrote through a parent link")

    def test_merge_and_block_leaves_swapped_for_inside_symlinks_are_refused(self):
        for name in ("settings.json", "rc"):
            leaf = self.home / "owned" / name
            leaf.unlink()
            leaf.symlink_to(self.user_files / name)
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertUserFilesIntact("uninstall rewrote a file behind a leaf link")

    def test_a_neva_symlink_replaced_by_a_real_file_is_not_deleted(self):
        link = self.home / "owned" / "link"
        link.unlink()
        link.write_text("the user put a real file here\n", encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertEqual(link.read_text(encoding="utf-8"), "the user put a real file here\n")

    def test_negative_control_an_untouched_install_uninstalls_cleanly(self):
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertFalse((self.home / "owned").exists())
        self.assertUserFilesIntact("a clean uninstall touched unrelated files")


class TestPreexistingInsideLinks(Outside):
    def test_a_dotfiles_link_present_at_install_is_kept_and_uninstall_restores_it(self):
        real = self.home / "dotfiles" / "claude"
        real.mkdir(parents=True)
        (real / "settings.json").write_text('{"model": "opus"}\n', encoding="utf-8")
        (self.home / ".claude").symlink_to(real, target_is_directory=True)
        before = snapshot(self.home)
        code, output = self.install(harness="claude")
        self.assertEqual(code, 0, output)
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertEqual(snapshot(self.home), before, "the dotfiles layout did not come back")


class TestGuardPrimitive(Outside):
    def test_guard_names_the_first_symlink_under_home(self):
        (self.home / ".claude").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(core.BoundaryError) as caught:
            core.guard_destination(self.home / ".claude" / "settings.json")
        self.assertIn(str(self.home / ".claude"), str(caught.exception))
        self.assertIn("fix:", str(caught.exception))

    def test_guard_without_following_the_leaf_allows_a_link_neva_will_replace(self):
        link = self.home / "link.md"
        link.symlink_to(self.outside / "anything.md")
        self.assertEqual(core.guard_destination(link, follow_leaf=False), link)
        with self.assertRaises(core.BoundaryError):
            core.guard_destination(link)

    def test_guard_refuses_a_lexical_traversal(self):
        with self.assertRaises(core.BoundaryError):
            core.guard_destination(self.home / ".." / "outside" / "x")


if __name__ == "__main__":
    import unittest
    unittest.main()
