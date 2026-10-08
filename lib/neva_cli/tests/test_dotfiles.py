"""A dotfiles link at a merged or appended destination survives install and uninstall intact.

The mainstream layout: ~/.claude/settings.json and ~/.profile are symlinks into a ~/dotfiles
repository. Neva merges its keys and appends its block through the link into the file the link
points at, and never replaces the link with a plain file. After uninstall the link must point at
the same target and the target must hold the same bytes as before install.
"""
import json
import os

from neva_cli.tests.harness import Sandbox, snapshot
from neva_cli.tests.test_install import SOURCES, adapter

SETTINGS = '{"model": "opus", "env": {"FOO": "1"}}\n'
PROFILE = "export EDITOR=vim\n"
TOML = 'model = "gpt"\n'


class Dotfiles(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", adapter(), SOURCES)
        dots = self.home / "dotfiles"
        dots.mkdir()
        self.targets = {"settings": dots / "claude-settings.json", "profile": dots / "profile",
                        "toml": dots / "codex-config.toml", "codex": dots / "codex-settings.json"}
        self.targets["settings"].write_text(SETTINGS, encoding="utf-8")
        self.targets["profile"].write_text(PROFILE, encoding="utf-8")
        self.targets["toml"].write_text(TOML, encoding="utf-8")
        self.targets["codex"].write_text('{"editor": "vim"}\n', encoding="utf-8")
        self.targets["settings"].chmod(0o640)
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        self.links = {"settings": self.home / ".claude" / "settings.json",
                      "profile": self.home / ".profile",
                      "toml": self.home / ".codex" / "config.toml",
                      "codex": self.home / ".codex" / "settings.json"}
        for name, link in self.links.items():
            link.symlink_to(self.targets[name])
        self.before_links = {name: os.readlink(link) for name, link in self.links.items()}
        self.before_bytes = {name: path.read_bytes() for name, path in self.targets.items()}
        self.before = snapshot(self.home)

    def assertLinksIntact(self, when):
        for name, link in self.links.items():
            with self.subTest(link=name, when=when):
                self.assertTrue(link.is_symlink(), name + " is no longer a symlink " + when)
                self.assertEqual(os.readlink(link), self.before_links[name])


class TestDotfilesLinks(Dotfiles):
    def test_install_writes_through_the_links_and_keeps_them(self):
        code, output = self.install(harness="all")
        self.assertEqual(code, 0, output)
        self.assertLinksIntact("after install")
        settings = json.loads(self.targets["settings"].read_text(encoding="utf-8"))
        self.assertEqual(settings["env"]["FOO"], "1")
        self.assertIn("NEVA_PLUGINS", settings["env"])
        self.assertIn("# neva begin codex", self.targets["profile"].read_text(encoding="utf-8"))
        self.assertIn("[tool.neva]", self.targets["toml"].read_text(encoding="utf-8"))

    def test_uninstall_leaves_each_link_and_its_target_byte_identical(self):
        self.install(harness="all")
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertLinksIntact("after uninstall")
        for name, path in self.targets.items():
            with self.subTest(target=name):
                self.assertEqual(path.read_bytes(), self.before_bytes[name],
                                 name + " target bytes changed across install and uninstall")
        self.assertEqual(self.targets["settings"].stat().st_mode & 0o777, 0o640)
        self.assertEqual(snapshot(self.home), self.before, "HOME is not byte identical")

    def test_repair_writes_through_the_link_too(self):
        self.install(harness="claude")
        data = json.loads(self.targets["settings"].read_text(encoding="utf-8"))
        data["env"]["NEVA_PLUGINS"] = "tampered"
        self.targets["settings"].write_text(json.dumps(data), encoding="utf-8")
        code, output = self.repair()
        self.assertEqual(code, 0, output)
        self.assertLinksIntact("after repair")
        self.assertEqual(json.loads(self.targets["settings"].read_text(encoding="utf-8"))["env"]["NEVA_PLUGINS"],
                         "core")
        self.uninstall()
        self.assertLinksIntact("after uninstall")

    def test_a_link_repointed_after_install_is_refused(self):
        self.install(harness="claude")
        other = self.home / "dotfiles" / "other.json"
        other.write_text('{"other": true}\n', encoding="utf-8")
        link = self.links["settings"]
        link.unlink()
        link.symlink_to(other)
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn(str(link), output)
        self.assertEqual(other.read_text(encoding="utf-8"), '{"other": true}\n')

    def test_negative_control_the_comparison_sees_a_link_turned_into_a_file(self):
        self.install(harness="claude")
        self.uninstall()
        link = self.links["settings"]
        link.unlink()
        link.write_text(SETTINGS, encoding="utf-8")
        self.assertNotEqual(snapshot(self.home), self.before)


if __name__ == "__main__":
    import unittest
    unittest.main()
