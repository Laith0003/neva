"""A refusal anywhere in a contract means nothing of that harness is written.

Every destination is read, shape-checked and boundary-checked before the first write, so an
owner file Neva cannot merge into (here an opencode.json with a // comment, which the strict
JSON reader refuses) stops the whole harness instead of leaving it half installed.
"""
import unittest

from neva_cli import core
from neva_cli.tests.harness import Sandbox

SHIPPED = core.REPO_ROOT / "adapters"
JSONC = '{\n  // my model\n  "model": "owner/model"\n}\n'


class TestPreflight(Sandbox):
    def assertNothingWritten(self, harness, before):
        code, output = self.install(harness=harness)
        self.assertEqual(1, code, output)
        self.assertIn("not valid JSON", output)
        self.assertHomeUnchanged(before, "a refused install wrote part of the harness:")
        self.assertFalse(core.state_path().exists(), "a refused install wrote a manifest")

    def test_shipped_opencode_with_a_commented_config_writes_nothing(self):
        self.env({"NEVA_ADAPTERS_DIR": str(SHIPPED)})
        path = self.home / ".config" / "opencode" / "opencode.json"
        path.parent.mkdir(parents=True)
        path.write_text(JSONC, encoding="utf-8")
        self.assertNothingWritten("opencode", self.snapshot_home())

    def test_a_late_refusal_in_a_fixture_contract_writes_nothing(self):
        self.write_adapter("codex", {"harness": "codex", "entries": [
            {"src": "AGENTS.md", "dest": "~/.codex/AGENTS.md", "mode": "copy"},
            {"src": "rules.md", "dest": "~/.codex/RULES.md", "mode": "append-block", "key": "neva-core"},
            {"src": "settings.json", "dest": "~/.codex/settings.json", "mode": "merge-json", "key": "neva"}]},
            {"AGENTS.md": "# Neva\\n", "rules.md": "rules\\n", "settings.json": '{"neva": {"a": 1}}'})
        settings = self.home / ".codex" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"broken": ', encoding="utf-8")
        self.assertNothingWritten("codex", self.snapshot_home())

    def test_negative_control_a_clean_contract_still_installs(self):
        self.write_adapter("codex", {"harness": "codex", "entries": [
            {"src": "AGENTS.md", "dest": "~/.codex/AGENTS.md", "mode": "copy"}]}, {"AGENTS.md": "# Neva\\n"})
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertTrue((self.home / ".codex" / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
