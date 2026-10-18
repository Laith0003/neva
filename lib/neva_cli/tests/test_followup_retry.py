"""Directory cleanup after a refused uninstall."""
from neva_cli import core
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_install import SOURCES, adapter


class TestRetryDirectoryCleanup(Sandbox):
    def test_retry_removes_directories_owned_by_successful_first_pass_entries(self):
        contract = adapter(entries=[
            {"src": "AGENTS.md", "dest": "~/rules/first.md", "mode": "copy"},
            {"src": "AGENTS.md", "dest": "~/rules/second.md", "mode": "copy"},
        ], post=[])
        self.write_adapter("codex", contract, SOURCES)
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(code, 0, output)
        refused = self.home / "rules" / "second.md"
        refused.write_text("owner edited this file\n", encoding="utf-8")
        code, output = self.uninstall()
        self.assertEqual(code, 1, output)
        self.assertIn("was edited", output)
        self.assertFalse((self.home / "rules" / "first.md").exists())
        self.assertTrue(refused.exists())
        refused.unlink()
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertIn("already gone", output)
        self.assertHomeUnchanged(before)
        self.assertFalse(core.state_path().exists())
