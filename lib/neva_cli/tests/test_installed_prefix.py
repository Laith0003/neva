"""The neva a buyer actually runs is ~/.local/bin/neva, a link into the install prefix.

install.sh builds that prefix from a checkout with lib/install-tools.sh. These tests build it
with the same function, delete the checkout, and then drive the installed binary as a real
process. Everything the CLI needs (rules, hooks, the marketplace manifest) has to live in the
prefix, because REPO_ROOT for that binary is the prefix and the checkout may be long gone.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from neva_cli import core
from neva_cli.tests.harness import Sandbox, difference, snapshot

REPO = core.REPO_ROOT
SHIPPED = ("bin", "lib", "plugins", ".claude-plugin", "VERSION")
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")


def make_checkout(root, skip=()):
    checkout = root / "checkout"
    checkout.mkdir()
    for name in SHIPPED:
        if name in skip:
            continue
        source = REPO / name
        if source.is_dir():
            shutil.copytree(source, checkout / name, symlinks=True, ignore=IGNORE)
        elif source.is_file():
            shutil.copy2(source, checkout / name)
    return checkout


def run_install_tools(checkout, prefix, linkdir):
    """The exact helper install.sh sources at step 2."""
    return subprocess.run(
        ["bash", "-c", '. "$1/lib/install-tools.sh" && neva_install_tools "$1" "$2" "$3"',
         "install-tools", str(checkout), str(prefix), str(linkdir)],
        capture_output=True, text=True, timeout=120)


class InstalledPrefix(Sandbox):
    def setUp(self):
        super().setUp()
        checkout = make_checkout(self.root)
        self.prefix = self.home / ".local" / "neva"
        self.linkdir = self.home / ".local" / "bin"
        result = run_install_tools(checkout, self.prefix, self.linkdir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The buyer's checkout is gone: a downloaded zip deleted, a clone moved.
        shutil.rmtree(checkout)
        # bin/neva runs under `env python3`; pin that to the interpreter running these tests.
        (self.binroot / "python3").symlink_to(sys.executable)
        self.neva = self.linkdir / "neva"
        self.assertTrue(self.neva.is_symlink(), "install-tools did not link neva into ~/.local/bin")

    def run_neva(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", NEVA_SKIP_VAULT_DOCTOR="1")
        result = subprocess.run([str(self.neva)] + list(args), capture_output=True, text=True,
                                env=env, timeout=120)
        return result.returncode, result.stdout + result.stderr


class TestInstalledCli(InstalledPrefix):
    def test_the_installed_cli_copies_the_rules(self):
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 0, output)
        common = self.home / ".claude" / "rules" / "neva" / "common"
        self.assertTrue(list(common.glob("*.md")), "the installed CLI found no rule sources:\n" + output)

    def test_the_installed_cli_registers_its_own_prefix_as_the_marketplace(self):
        code, output = self.run_neva("install", "--harness", "claude", "--plugins", "core,web", "--yes")
        self.assertEqual(code, 0, output)
        state = self.claude_state()
        self.assertEqual([(item["name"], item["source"]) for item in state["marketplaces"]],
                         [("neva", str(self.prefix.resolve()))], output)
        self.assertEqual(sorted(item["id"] for item in state["plugins"]),
                         ["neva-core@neva", "neva-web@neva"])

    def test_the_installed_doctor_is_green_after_the_installed_install(self):
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 0, output)
        code, output = self.run_neva("doctor", "--no-vault")
        self.assertEqual(code, 0, "installed doctor went red:\n" + output)
        self.assertNotIn("FAIL", output)
        self.assertIn("Claude hook dispatcher runs", output)

    def seed_user_files(self):
        """Content a real buyer already has, which uninstall must hand back byte for byte."""
        claude = self.home / ".claude"
        (claude / "rules").mkdir(parents=True)
        # A dotfiles layout: settings.json is a link into a repository Neva must never cut out.
        (self.home / "dotfiles").mkdir()
        settings = self.home / "dotfiles" / "claude-settings.json"
        settings.write_text('{\n  "model": "opus",\n  "env": {"MINE": "keep"}\n}\n', encoding="utf-8")
        settings.chmod(0o640)
        (claude / "settings.json").symlink_to(settings)
        (claude / "rules" / "mine.md").write_text("my own rule\n", encoding="utf-8")
        (claude / "notes-link").symlink_to(self.home / "notes")
        (self.home / "notes").write_text("notes\n", encoding="utf-8")

    def install_and_uninstall(self):
        code, output = self.run_neva("install", "--harness", "claude", "--plugins", "core,web", "--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("NEVA_PLUGINS", (self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue((self.home / ".claude" / "settings.json").is_symlink(), "install cut the dotfiles link")
        code, output = self.run_neva("uninstall", "--yes")
        self.assertEqual(code, 0, output)

    def test_the_installed_cli_takes_itself_back_out_byte_for_byte(self):
        self.seed_user_files()
        before = snapshot(self.home)
        self.install_and_uninstall()
        self.assertEqual(difference(before, snapshot(self.home)), [],
                         "the installed uninstall did not restore HOME byte for byte")
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.claude_state(), {"marketplaces": [], "plugins": []})

    def test_with_the_default_data_dir_only_backups_are_retained(self):
        os.environ.pop("NEVA_DATA_DIR")
        self.seed_user_files()
        before = snapshot(self.home)
        self.install_and_uninstall()
        data = self.home / ".local" / "share"
        after = snapshot(self.home, skip=[data])
        self.assertEqual(after, before, "outside the retained data directory, HOME changed")
        retained = sorted(str(path.relative_to(data / "neva")) for path in (data / "neva").iterdir())
        self.assertEqual(retained, ["backups"], "uninstall kept more than its backups")
        self.assertTrue(list((data / "neva" / "backups").glob("*/*settings.json.*")))

    def test_negative_controls_the_comparison_sees_bytes_modes_and_link_targets(self):
        self.seed_user_files()
        before = snapshot(self.home)
        self.install_and_uninstall()
        settings = self.home / "dotfiles" / "claude-settings.json"
        link = self.home / ".claude" / "notes-link"
        cases = (
            ("bytes", lambda: settings.write_text('{"model": "opus"}\n', encoding="utf-8")),
            ("mode", lambda: settings.chmod(0o644)),
            ("link target", lambda: (link.unlink(), link.symlink_to(self.home / "elsewhere"))),
        )
        for label, mutate in cases:
            mutate()
            with self.subTest(changed=label):
                self.assertIn("changed " + (".claude/notes-link" if label == "link target"
                                            else "dotfiles/claude-settings.json"),
                              difference(before, snapshot(self.home)))

    def test_negative_control_a_prefix_without_rules_fails_by_name(self):
        shutil.rmtree(self.prefix / "plugins" / "neva-core" / "rules")
        code, output = self.run_neva("install", "--harness", "claude", "--yes")
        self.assertEqual(code, 1, output)
        self.assertIn("no neva-core rules", output)
        self.assertIn("fix:", output)


class TestInstallToolsPathSafety(Sandbox):
    """install-tools refuses a prefix or bin directory that a symlink would steer elsewhere."""

    def setUp(self):
        super().setUp()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.prefix = self.home / ".local" / "neva"
        self.linkdir = self.home / ".local" / "bin"
        self.prefix.parent.mkdir(parents=True)
        (self.binroot / "python3").symlink_to(sys.executable)

    def test_a_prefix_with_shell_metacharacters_is_sourced_literally(self):
        weird = self.home / 'we$(touch${IFS}MARKER)ir`touch${IFS}MARKTWO`d "q" & a|b'
        weird.mkdir()
        prefix, linkdir = weird / "neva", weird / "bin"
        result = run_install_tools(make_checkout(self.root), prefix, linkdir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tool = prefix / "bin" / "alert"
        line = next(row for row in tool.read_text(encoding="utf-8").splitlines()
                    if row.startswith(". ") and "lib/config.sh" in row)
        self.assertEqual(shlex.split(line), [".", str(prefix / "lib" / "config.sh")],
                         "the install path is not a single literal shell word: " + line)
        run = subprocess.run(["bash", str(tool)], cwd=str(self.root), capture_output=True, text=True,
                             timeout=60)
        self.assertIn("config missing", run.stderr, "config.sh at the literal path was not sourced")
        self.assertEqual(sorted(path.name for path in self.root.rglob("MARK*")), [],
                         "text in the install path ran as a command")

    def assertRefused(self, result, path):
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "install-tools reported success:\n" + output)
        self.assertIn(str(path), output)
        self.assertIn("fix:", output)
        self.assertEqual(snapshot(self.outside), {}, "install-tools wrote outside the prefix")

    def test_a_prefix_symlinked_outside_is_refused(self):
        self.prefix.symlink_to(self.outside, target_is_directory=True)
        self.assertRefused(run_install_tools(make_checkout(self.root), self.prefix, self.linkdir),
                           self.prefix)

    def test_a_prefix_symlinked_inside_home_is_refused_too(self):
        real = self.home / "elsewhere"
        real.mkdir()
        self.prefix.symlink_to(real, target_is_directory=True)
        result = run_install_tools(make_checkout(self.root), self.prefix, self.linkdir)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(real.iterdir()), [])

    def test_a_managed_child_of_the_prefix_symlinked_outside_is_refused(self):
        self.prefix.mkdir()
        (self.prefix / "bin").symlink_to(self.outside, target_is_directory=True)
        self.assertRefused(run_install_tools(make_checkout(self.root), self.prefix, self.linkdir),
                           self.prefix / "bin")

    def test_a_deeper_link_inside_a_managed_child_is_refused(self):
        (self.prefix / "plugins").mkdir(parents=True)
        (self.prefix / "plugins" / "neva-core").symlink_to(self.outside, target_is_directory=True)
        self.assertRefused(run_install_tools(make_checkout(self.root), self.prefix, self.linkdir),
                           self.prefix / "plugins" / "neva-core")

    def test_a_bin_dir_symlinked_outside_is_refused(self):
        self.linkdir.symlink_to(self.outside, target_is_directory=True)
        self.assertRefused(run_install_tools(make_checkout(self.root), self.prefix, self.linkdir),
                           self.linkdir)

    def test_a_prefix_outside_home_is_refused(self):
        result = run_install_tools(make_checkout(self.root), self.outside / "neva", self.linkdir)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.outside / "neva").exists())

    def test_a_failed_copy_is_a_failure(self):
        result = run_install_tools(make_checkout(self.root, skip=("plugins",)), self.prefix, self.linkdir)
        self.assertNotEqual(result.returncode, 0, "a missing plugins tree was reported as success")

    def test_negative_control_a_clean_prefix_installs(self):
        result = run_install_tools(make_checkout(self.root), self.prefix, self.linkdir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.prefix / ".claude-plugin" / "marketplace.json").is_file())


if __name__ == "__main__":
    import unittest
    unittest.main()
