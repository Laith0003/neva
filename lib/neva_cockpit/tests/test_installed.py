"""The installed CLI, not the checkout: install.sh into a throwaway HOME, then run the symlink.

Review finding H1: the cockpit imported the hooks runtime from a checkout-relative path that the
installer never copied, and bin/neva imports every command before parsing arguments, so the
installed `neva --help` died with ModuleNotFoundError. These tests run exactly what a buyer runs.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def clean_env(home):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("NEVA_", "XDG_")) and k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return env


def cockpit_env(home):
    env = clean_env(home)
    env.update(NEVA_DATA_DIR=str(home / "data"), NEVA_STATE_DIR=str(home / "state"),
               NEVA_CONFIG=str(home / "no-identity.env"))
    return env


class InstalledEntryPointTests(unittest.TestCase):
    def test_installed_symlink_runs_help_and_cockpit_json(self):
        with tempfile.TemporaryDirectory(prefix="neva-installed-") as temporary:
            home = Path(temporary)
            env = clean_env(home)
            env.update(NEVA_NONINTERACTIVE="1", NEVA_SKIP_SCHEDULE_ENABLE="1",
                       NEVA_HARNESS="none", OWNER_NAME="Fixture",
                       VAULT_PATH=str(home / "vault"), WORKSPACE_PATH=str(home / "workspace"))
            installed = subprocess.run(["bash", str(REPO / "install.sh")], env=env, cwd=home,
                                       capture_output=True, text=True, timeout=300)
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            entry = home / ".local" / "bin" / "neva"
            self.assertTrue(entry.is_symlink(), "install.sh did not link neva into ~/.local/bin")

            helped = subprocess.run([str(entry), "--help"], env=cockpit_env(home), cwd=home,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(helped.returncode, 0, helped.stderr)
            self.assertIn("cockpit", helped.stdout)

            snap = subprocess.run([str(entry), "cockpit", "--json"], env=cockpit_env(home),
                                  cwd=home, capture_output=True, text=True, timeout=60)
            self.assertEqual(snap.returncode, 0, snap.stderr)
            data = json.loads(snap.stdout)
            self.assertEqual(data["sessions"], [])
            self.assertIn("omniroute", data["health"])

            prefix = home / ".local" / "neva"
            for relative in ("plugins/neva-core/hooks/neva_hooks/common.py",
                             "plugins/neva-core/rules/README.md",
                             ".claude-plugin/marketplace.json"):
                self.assertTrue((prefix / relative).is_file(), "not installed: " + relative)
            # Adapters are owned by another branch and may not exist in this checkout; whatever
            # adapter contracts the checkout has must land in the prefix.
            shipped = sorted(p.relative_to(REPO).as_posix()
                             for p in (REPO / "adapters").rglob("install.json"))
            for relative in shipped:
                self.assertTrue((prefix / relative).is_file(), "not installed: " + relative)
            self.assertEqual(list(prefix.rglob("__pycache__")), [],
                             "install.sh copied bytecode caches into the prefix")


class MissingHooksRuntimeTests(unittest.TestCase):
    """A prefix laid out the way the old installer laid it out: bin and lib, no plugins."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="neva-partial-")
        self.home = Path(self.tmp.name)
        self.prefix = self.home / "prefix"
        ignore = shutil.ignore_patterns("__pycache__", "tests")
        shutil.copytree(REPO / "bin", self.prefix / "bin", ignore=ignore)
        shutil.copytree(REPO / "lib", self.prefix / "lib", ignore=ignore)
        self.neva = self.prefix / "bin" / "neva"

    def tearDown(self):
        self.tmp.cleanup()

    def test_other_commands_still_start_without_the_hooks_runtime(self):
        helped = subprocess.run([str(self.neva), "--help"], env=cockpit_env(self.home),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(helped.returncode, 0, helped.stderr)
        self.assertIn("cockpit", helped.stdout)

    def test_cockpit_names_the_missing_runtime_and_the_fix(self):
        snap = subprocess.run([str(self.neva), "cockpit", "--json"], env=cockpit_env(self.home),
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(snap.returncode, 0)
        self.assertNotIn("Traceback", snap.stderr)
        self.assertIn("plugins/neva-core/hooks", snap.stderr)
        self.assertIn("fix: re-run install.sh", snap.stderr)


if __name__ == "__main__":
    unittest.main()
