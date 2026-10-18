"""Regression checks for owner mapping preservation."""
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_install import SOURCES, adapter

class TestIdenticalOwnerJson(Sandbox):
    def test_identical_json_keeps_owner_bytes_through_install_twice_and_uninstall(self):
        self.check_owner_bytes(False)

    def test_identical_linked_json_keeps_owner_bytes_and_link(self):
        self.check_owner_bytes(True)

    def check_owner_bytes(self, linked):
        entry = {"src": "settings.json", "dest": "~/.codex/settings.json", "mode": "merge-json", "key": "neva.profile"}
        self.write_adapter("codex", adapter(entries=[entry], post=[]), SOURCES)
        target = self.home / ".codex" / "settings.json"
        target.parent.mkdir()
        original = b'{ "owner": true, "neva": {"profile":"standard"} }\n'
        if linked:
            owner = self.home / "owner.json"
            owner.write_bytes(original)
            target.symlink_to(owner)
        else:
            target.write_bytes(original)
        for unused in range(2):
            code, output = self.install(harness="codex")
            self.assertEqual(code, 0, output)
            self.assertIn("codex", output)
            self.assertEqual(target.read_bytes(), original)
        code, output = self.uninstall(harness="codex")
        self.assertEqual(code, 0, output)
        self.assertIn(str(target), output)
        self.assertEqual(target.read_bytes(), original)
        if linked:
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.readlink(), owner)

