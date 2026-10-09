"""A merge-toml key may quote a part, as TOML does: plugins."neva-core@neva".

Codex enables a plugin under a table whose name holds an @, which TOML only allows quoted. The
key is split the way TOML splits it, so the quoted part is one key and never three.
"""
import unittest

from neva_cli import core
from neva_cli.tests.harness import Sandbox

SOURCE = '[plugins."neva-core@neva"]\nenabled = true\n'
OWNER = 'model = "owner-model"\n\n[plugins."other@market"]\nenabled = true\n'
KEY = 'plugins."neva-core@neva"'


class TestQuotedTomlKeys(Sandbox):
    def setUp(self):
        super().setUp()
        self.write_adapter("codex", {"harness": "codex", "entries": [
            {"src": "config.toml", "dest": "~/.codex/config.toml", "mode": "merge-toml", "key": KEY}]},
            {"config.toml": SOURCE})
        self.config = self.home / ".codex" / "config.toml"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(OWNER, encoding="utf-8")

    def test_a_quoted_part_is_one_key(self):
        self.assertEqual(["plugins", "neva-core@neva"], core.key_parts(KEY))
        self.assertEqual(["env", "NEVA_PLUGINS"], core.key_parts("env.NEVA_PLUGINS"))

    def test_install_twice_then_uninstall_keeps_the_owner_table(self):
        before = self.snapshot_home()
        for _ in (1, 2):
            code, output = self.install(harness="codex")
            self.assertEqual(code, 0, output)
        config = core.read_toml(self.config)
        self.assertTrue(config["plugins"]["neva-core@neva"]["enabled"])
        self.assertTrue(config["plugins"]["other@market"]["enabled"])
        self.assertEqual("owner-model", config["model"])
        code, output = self.uninstall()
        self.assertEqual(code, 0, output)
        self.assertHomeUnchanged(before)


if __name__ == "__main__":
    unittest.main()
