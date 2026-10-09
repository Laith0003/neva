"""A copy or symlink entry whose src is a directory installs every file under it, one by one.

Shipped adapters copy whole trees (Codex agent roles, OpenCode agents, commands and skills).
Each file becomes its own manifest entry, so repair and uninstall treat it like any other copy,
and uninstall leaves HOME byte identical. A symlink inside the tree is refused, never followed.
"""
import os
import unittest

from neva_cli.tests.harness import Sandbox

TREE = {"agents/planner.toml": 'name = "planner"\n', "agents/deep/reviewer.toml": 'name = "reviewer"\n'}


class TestDirectorySources(Sandbox):
    def setUp(self):
        super().setUp()
        self.adapter = self.write_adapter("codex", {"harness": "codex", "entries": [
            {"src": "agents", "dest": "~/.codex/neva/agents", "mode": "copy"}]}, TREE)
        self.dest = self.home / ".codex" / "neva" / "agents"

    def test_every_file_lands_and_is_recorded(self):
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertEqual('name = "planner"\n', (self.dest / "planner.toml").read_text(encoding="utf-8"))
        self.assertEqual('name = "reviewer"\n', (self.dest / "deep" / "reviewer.toml").read_text(encoding="utf-8"))
        self.assertEqual(2, len(self.entries("codex")))

    def test_uninstall_leaves_home_byte_identical(self):
        before = self.snapshot_home()
        self.install(harness="codex")
        self.install(harness="codex")
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before)

    def test_an_owner_file_in_the_same_directory_survives(self):
        self.dest.mkdir(parents=True)
        (self.dest / "mine.toml").write_text("mine\n", encoding="utf-8")
        before = self.snapshot_home()
        self.install(harness="codex")
        self.uninstall()
        self.assertHomeUnchanged(before)

    def test_an_owner_file_at_a_tree_destination_is_refused_not_replaced(self):
        (self.dest / "deep").mkdir(parents=True)
        (self.dest / "deep" / "reviewer.toml").write_text("the owner's reviewer\n", encoding="utf-8")
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(1, code, output)
        self.assertIn("reviewer.toml", output)
        self.assertIn("not Neva's", output)
        self.assertHomeUnchanged(before, "a refused tree install wrote files:")

    def test_a_symlink_inside_the_source_tree_is_refused(self):
        outside = self.root / "private.txt"
        outside.write_text("private\n", encoding="utf-8")
        os.symlink(outside, self.adapter / "agents" / "leak.toml")
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(1, code, output)
        self.assertIn("symlink", output)
        self.assertHomeUnchanged(before, "files were written before the symlink refusal:")

    def test_os_junk_in_a_tree_is_not_installed(self):
        for junk in (".DS_Store", "._planner.toml", "Thumbs.db"):
            (self.adapter / "agents" / junk).write_text("junk\n", encoding="utf-8")
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertEqual(2, len(self.entries("codex")))
        self.assertFalse((self.dest / ".DS_Store").exists())

    def test_an_absolute_or_parent_src_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("private\n", encoding="utf-8")
        for src in (str(outside), "../../outside", "agents/../../outside"):
            with self.subTest(src=src):
                self.write_adapter("codex", {"harness": "codex", "entries": [
                    {"src": src, "dest": "~/.codex/x", "mode": "copy"}]})
                before = self.snapshot_home()
                code, output = self.install(harness="codex")
                self.assertEqual(1, code, output)
                self.assertIn("src", output)
                self.assertHomeUnchanged(before)

    def test_dry_run_writes_nothing(self):
        before = self.snapshot_home()
        code, output = self.install(harness="codex", dry_run=True)
        self.assertEqual(code, 0, output)
        self.assertIn("would manage 2 entries", output)
        self.assertHomeUnchanged(before)


if __name__ == "__main__":
    unittest.main()
