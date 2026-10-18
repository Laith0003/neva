"""Codex paths: CODEX_HOME defaults to ~/.codex, and config.toml gets real paths, not ${VAR} text."""
import os
import unittest.mock

from neva_cli import core
from neva_cli.tests.harness import Sandbox
from neva_cli.tests.test_shipped_adapters import OWNER_CONFIG, OWNER_RULES, SHIPPED


class CodexSandbox(Sandbox):
    def setUp(self):
        super().setUp()
        self.env({"NEVA_ADAPTERS_DIR": str(SHIPPED)})
        for name in ("CODEX_HOME", "NEVA_ROOT"):
            self.unset(name)

    def unset(self, name):
        old = os.environ.pop(name, None)
        self.addCleanup(self._restore, name, old)

    def put(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestCodexHomeDefault(CodexSandbox):
    def test_install_without_codex_home_uses_dot_codex(self):
        before = self.snapshot_home()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertNotIn("unset variable", output)
        self.assertTrue((self.home / ".codex" / "AGENTS.md").is_file())
        self.assertTrue((self.home / ".codex" / "neva" / "agents" / "architect.toml").is_file())
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)

    def test_exported_codex_home_still_wins(self):
        self.env({"CODEX_HOME": str(self.home / "elsewhere")})
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertTrue((self.home / "elsewhere" / "AGENTS.md").is_file())
        self.assertFalse((self.home / ".codex").exists())

    def test_other_unset_variables_are_still_refused(self):
        with self.assertRaises(core.AdapterError) as caught:
            core.expand_destination("${NEVA_TEST_NOT_SET}/x")
        self.assertIn("unset variable", str(caught.exception))


class TestCodexConfigPaths(CodexSandbox):
    def toml_entries(self):
        return [entry for entry in self.entries("codex") if entry["kind"] == "merge-toml"]

    def test_config_toml_gets_real_paths_and_the_manifest_records_them(self):
        config = self.put(".codex/config.toml", OWNER_CONFIG)
        before = self.snapshot_home()
        for run in (1, 2):
            code, output = self.install(harness="codex")
            self.assertEqual(0, code, "run " + str(run) + ":\n" + output)
        text = config.read_text(encoding="utf-8")
        self.assertNotIn("${", text)
        self.assertTrue(text.startswith(OWNER_CONFIG))
        parsed = core.read_toml(config)
        self.assertEqual(str(core.REPO_ROOT), parsed["marketplaces"]["neva"]["source"])
        self.assertEqual(str(self.home / ".codex" / "neva" / "agents" / "architect.toml"),
                         parsed["agents"]["architect"]["config_file"])
        for entry in self.toml_entries():
            self.assertNotIn("${", str(entry["value"]), entry["key"])
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("nothing to repair", output)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)

    def test_exported_neva_root_is_written(self):
        self.env({"NEVA_ROOT": str(self.root / "checkout")})
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        parsed = core.read_toml(self.home / ".codex" / "config.toml")
        self.assertEqual(str(self.root / "checkout"), parsed["marketplaces"]["neva"]["source"])

    def literal_install(self):
        """An install as the main-era installer left it: ${VAR} text in config.toml and the manifest."""
        with unittest.mock.patch.object(core, "expand_value", side_effect=lambda value: value):
            code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertIn("${NEVA_ROOT}", (self.home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    def test_old_literal_manifest_still_repairs_and_uninstalls(self):
        self.put(".codex/config.toml", OWNER_CONFIG)
        self.put(".codex/AGENTS.md", OWNER_RULES)
        before = self.snapshot_home()
        self.literal_install()
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("nothing to repair", output)
        config = self.home / ".codex" / "config.toml"
        text = config.read_text(encoding="utf-8")
        config.write_text(text.replace('\n[plugins."neva-core@neva"]\nenabled = true\n', ""), encoding="utf-8")
        self.assertNotIn("neva-core@neva", config.read_text(encoding="utf-8"))
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("repaired", output)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)

    def test_reinstall_over_old_literal_install_writes_real_paths(self):
        config = self.put(".codex/config.toml", OWNER_CONFIG)
        before = self.snapshot_home()
        self.literal_install()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        text = config.read_text(encoding="utf-8")
        self.assertNotIn("${", text)
        self.assertTrue(text.startswith(OWNER_CONFIG))
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("nothing to repair", output)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)


OLD_BEGIN, OLD_END = "# neva begin neva-core", "# neva end neva-core"
NEW_BEGIN, NEW_END = "<!-- neva begin neva-core -->", "<!-- neva end neva-core -->"


class TestMarkdownBlockMarkers(CodexSandbox):
    def agents(self):
        return (self.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")

    def test_markdown_block_uses_html_comment_markers(self):
        self.put(".codex/AGENTS.md", OWNER_RULES)
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        text = self.agents()
        self.assertEqual(1, text.count(NEW_BEGIN))
        self.assertEqual(1, text.count(NEW_END))
        self.assertNotIn(OLD_BEGIN, text)

    def old_marker_install(self):
        with unittest.mock.patch.object(core, "block_markers",
                                        side_effect=lambda key, destination=None: ("# neva begin " + key,
                                                                                   "# neva end " + key)):
            code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        self.assertIn(OLD_BEGIN, self.agents())

    def test_old_marker_install_repairs_and_uninstalls(self):
        self.put(".codex/AGENTS.md", OWNER_RULES)
        before = self.snapshot_home()
        self.old_marker_install()
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("nothing to repair", output)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)

    def test_old_marker_edited_block_is_repaired(self):
        self.put(".codex/AGENTS.md", OWNER_RULES)
        self.old_marker_install()
        path = self.home / ".codex" / "AGENTS.md"
        text = self.agents()
        path.write_text(text.replace(OLD_BEGIN + "\n", OLD_BEGIN + "\nOWNER-EDIT-MARK\n"), encoding="utf-8")
        code, output = self.repair()
        self.assertEqual(0, code, output)
        self.assertIn("repaired", output)
        text = self.agents()
        self.assertNotIn("OWNER-EDIT-MARK", text)
        self.assertEqual(1, text.count(NEW_BEGIN))
        self.assertNotIn(OLD_BEGIN, text)

    def test_reinstall_over_old_markers_swaps_them(self):
        self.put(".codex/AGENTS.md", OWNER_RULES)
        before = self.snapshot_home()
        self.old_marker_install()
        code, output = self.install(harness="codex")
        self.assertEqual(0, code, output)
        text = self.agents()
        self.assertTrue(text.startswith(OWNER_RULES))
        self.assertEqual(1, text.count(NEW_BEGIN))
        self.assertNotIn(OLD_BEGIN, text)
        code, output = self.uninstall()
        self.assertEqual(0, code, output)
        self.assertHomeUnchanged(before)
