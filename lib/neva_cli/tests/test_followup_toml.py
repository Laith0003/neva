"""TOML that the standard parser rejects is refused before any write."""
import unittest
import importlib.util
from neva_cli import core
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_install import SOURCES, adapter

@unittest.skipUnless(importlib.util.find_spec("tomllib"), "tomllib needs Python 3.11 or later")
class TestInvalidToml(Sandbox):
    def test_negative_control_valid_neighbours_parse(self):
        for document in ("a.b = 1\n[a.c]\nd = 2\n", "p = \"it's\"\n"):
            target = self.home / "valid.toml"
            target.write_text(document)
            self.assertTrue(core.read_toml(target))

    def test_standard_invalid_documents_are_refused_without_writes(self):
        self.write_adapter("codex", adapter(entries=[{"src": "config.toml", "dest": "~/.codex/config.toml", "mode": "merge-toml", "key": "tool.neva"}], post=[]), SOURCES)
        target = self.home / ".codex" / "config.toml"
        target.parent.mkdir()
        for document in ("a.b = 1\n[a]\n", "[a.b]\n[a]\nb.d = 2\n", "p = 'it''s'\n"):
            with self.subTest(document=document):
                target.write_text(document)
                code, output = self.install(harness="codex")
                self.assertEqual(code, 1, output)
                self.assertIn(str(target), output)
                self.assertIn("fix:", output)
                self.assertEqual(target.read_text(), document)

